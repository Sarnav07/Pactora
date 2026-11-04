let csrf = null;
let busy = false;
const $ = (id) => document.getElementById(id);
const message = (text) => { $("message").textContent = text; };
const money = (c) => new Intl.NumberFormat("en-US", {style:"currency", currency:"USD"}).format(c/100);
const node = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
};
async function api(path, method="GET", body) {
  const r = await fetch(path, {method, credentials:"same-origin", cache:"no-store",
    headers:{"Content-Type":"application/json", ...(csrf ? {"X-CSRF-Token":csrf}: {})},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || data.detail || "Private action refused");
  return data;
}
function action(text, fn, secondary=false, refreshAfter=true) {
  const b = node("button", text, secondary ? "secondary" : ""); b.type="button";
  b.addEventListener("click", async () => {
    b.disabled=true; message("");
    try { await fn(); if(refreshAfter) await refresh(); } catch(e) { message(e.message); }
    finally { b.disabled=false; }
  }); return b;
}
async function keyStore() {
  return new Promise((resolve,reject) => {
    const req = indexedDB.open("veilcart-device",1);
    req.onupgradeneeded=()=>req.result.createObjectStore("keys");
    req.onerror=()=>reject(new Error("Device key storage unavailable"));
    req.onsuccess=()=>resolve(req.result);
  });
}
async function deviceKeys() {
  const db = await keyStore();
  const saved = await new Promise((resolve,reject)=>{
    const r=db.transaction("keys").objectStore("keys").get("device");
    r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(new Error("Device key unreadable"));
  });
  if(saved){db.close();return saved;}
  const keys=await crypto.subtle.generateKey({name:"RSA-OAEP",modulusLength:3072,
    publicExponent:new Uint8Array([1,0,1]),hash:"SHA-256"},false,["encrypt","decrypt"]);
  await new Promise((resolve,reject)=>{
    const tx=db.transaction("keys","readwrite");tx.objectStore("keys").put(keys,"device");
    tx.oncomplete=resolve;tx.onerror=()=>reject(new Error("Device key storage failed"));
  });db.close();return keys;
}
const from64=(s)=>Uint8Array.from(atob(s), c=>c.charCodeAt(0));
async function publicPem(keys) {
  const raw=new Uint8Array(await crypto.subtle.exportKey("spki",keys.publicKey));
  const encoded=btoa(String.fromCharCode(...raw)).match(/.{1,64}/g).join("\n");
  return "-----BEGIN PUBLIC KEY-----\n"+encoded+"\n-----END PUBLIC KEY-----\n";
}
async function reveal(envelope) {
  const keys=await deviceKeys();
  const raw=await crypto.subtle.decrypt({name:"RSA-OAEP"},keys.privateKey,from64(envelope.key));
  const key=await crypto.subtle.importKey("raw",raw,"AES-GCM",false,["decrypt"]);
  const text=await crypto.subtle.decrypt({name:"AES-GCM",iv:from64(envelope.iv),
    additionalData:new TextEncoder().encode("veilcart-receipt-v1")},key,from64(envelope.ciphertext));
  return JSON.parse(new TextDecoder().decode(text));
}
function field(dl,label,value) {dl.append(node("dt",label),node("dd",String(value)));}
function renderJob(job, index) {
  const card=node("article",undefined,"job");const head=node("div",undefined,"jobhead");
  head.append(node("h3","Decision "+(index+1)),node("span",job.state.replaceAll("_"," "),"state"));card.append(head);
  if(job.details){
    const req=job.details.request;
    card.append(node("p",req.query+" · "+req.country+" · mandate "+money(req.budget_cents),"muted"));
    if(job.state==="awaiting_selection"){
      const chat=node("div",undefined,"chat"),check=node("input");check.type="checkbox";
      check.id="chat-"+job.reference;check.checked=job.chat_enabled;
      const label=node("label","Allow choice in chat (the model will know your selection)");label.htmlFor=check.id;
      check.onchange=async()=>{try{await api(`/api/jobs/${job.reference}/chat`,"POST",{enabled:check.checked});}
        catch(e){check.checked=!check.checked;message(e.message);}};chat.append(check,label);card.append(chat);
    }
    const options=node("div",undefined,"options");
    job.details.products.forEach((p,i)=>{
      const o=node("div",undefined,"option");o.append(node("h3",p.name),node("div",money(p.price_cents),"price"),
        node("p",p.package,"muted"),node("p",p.restrictions,"muted"));
      o.append(action("Select privately",()=>api(`/api/jobs/${job.reference}/select`,"POST",{option:i})));options.append(o);
    });card.append(options);
  }
  if(job.quote){
    const q=job.quote,box=node("div",undefined,"quote");box.append(node("h3","Review the exact purchase"));
    const dl=node("dl");field(dl,"Product",q.product.name);field(dl,"Total",money(q.total_cents));
    field(dl,"ZEC source",q.source_zat+" zatoshis");field(dl,"Wallet fee",q.fee_zat+" zatoshis");
    field(dl,"Maximum debit",q.max_debit_zat+" zatoshis");field(dl,"Checkout",q.checkout_mode);
    field(dl,"Route",q.destination_asset);field(dl,"Expires",new Date(q.expires_at*1000).toLocaleTimeString());
    box.append(dl,node("p",q.simulated ? "SIMULATION. No real money moves and no usable product is delivered." :
      "The merchant sees its order. The conversion service sees settlement metadata.","muted"));
    if(job.state==="awaiting_approval")box.append(action(q.simulated ? "Approve simulated purchase" : "Approve exact payment",async()=>{
      const keys=await deviceKeys();await api(`/api/jobs/${job.reference}/approve`,"POST",{
        quote_hash:job.quote_hash,device_public_key:await publicPem(keys)});
    }));card.append(box);
  }
  if(job.vault){
    const output=node("div");let visible=false;
    card.append(action("Reveal / hide private receipt",async()=>{
      visible=!visible;output.replaceChildren();
      if(visible){const data=await reveal(job.vault);output.append(node("pre",JSON.stringify(data,null,2),"secret"));}
    },true,false));
    card.append(action("Export encrypted receipt",async()=>{
      const blob=new Blob([JSON.stringify(job.vault)],{type:"application/json"});const url=URL.createObjectURL(blob);
      const a=node("a");a.href=url;a.download="pactora-encrypted-receipt.json";a.click();URL.revokeObjectURL(url);
    },true,false));card.append(output);
  }
  if(job.state==="uncertain")card.append(node("p","Execution needs reconciliation. Funds stay reserved. Do not pay again.","muted"));
  return card;
}
function renderMandate(m) {
  const card=node("article",undefined,"job");
  card.append(node("h3","Bounded shopping mandate"),node("p",m.state,"state"));
  const d=m.document,dl=node("dl");
  field(dl,"Merchant",d.merchant);field(dl,"Wallet / network",d.wallet_id+" / "+d.network);
  field(dl,"Per purchase / total",money(d.per_purchase_cents)+" / "+money(d.total_cents));
  field(dl,"Zatoshi caps (per / total)",d.per_purchase_zat+" / "+d.total_zat);
  field(dl,"Maximum purchases",d.max_purchases);field(dl,"Expires",new Date(d.expires_at*1000).toLocaleString());
  card.append(dl,node("p","Only these exact product/package combinations are permitted:"));
  m.products.forEach(p=>card.append(node("p",p.name+" · "+p.package+" · catalog "+money(p.price_cents))));
  card.append(node("p","Your hosted model sees your request, candidates and any choice it proposes. Approval allows matching purchases without another confirmation. Limits include fees.","muted"));
  if(d.merchant==="test_merchant")card.append(node("p","CONTROLLED TEST MERCHANT: actual Zcash test funds; no redeemable goods. Dollar figures are test accounting units, not an exchange rate.","muted"));
  if(d.merchant==="simulator")card.append(node("p","SIMULATOR: no funds move; codes are not redeemable.","muted"));
  if(m.state==="awaiting_approval")card.append(action("Approve bounded mandate",async()=>{
    const keys=await deviceKeys();await api(`/api/mandates/${m.reference}/approve`,"POST",{
      draft_hash:m.draft_hash,device_public_key:await publicPem(keys)});
  }));
  if(m.state!=="revoked")card.append(action("Revoke mandate",()=>api(`/api/mandates/${m.reference}/revoke`,"POST"),true));
  if(m.state!=="awaiting_approval")card.append(action("Recover stored receipt delivery",()=>api(`/api/mandates/${m.reference}/recover`,"POST"),true));
  m.receipts.forEach(envelope=>{
    const output=node("div");let visible=false;
    card.append(action("Reveal / hide mandate receipt",async()=>{visible=!visible;output.replaceChildren();
      if(visible)output.append(node("pre",JSON.stringify(await reveal(envelope),null,2),"secret"));},true,false),output);
  });return card;
}
async function refresh() {
  if(busy||!csrf)return;busy=true;
  try {
    // Preserve an explicitly revealed receipt until the next manual refresh.
    const jobs=await api("/api/jobs");$("jobs").replaceChildren(...jobs.map(renderJob));
    const mandates=await api("/api/mandates");$("jobs").prepend(...mandates.map(renderMandate));
    if(!jobs.length&&!mandates.length)$("jobs").append(node("div","No pending decisions. Ask your connected agent to search.","panel muted"));
  } finally {busy=false;}
}
$("login").onsubmit=async(e)=>{e.preventDefault();message("");try{
  const s=await api("/api/login","POST",{password:$("password").value});$("password").value="";csrf=s.csrf;
  $("environment").textContent=s.environment;$("login").hidden=true;$("workspace").hidden=false;await refresh();
}catch(e){message(e.message);}};
$("refresh").onclick=()=>refresh().catch(e=>message(e.message));
$("logout").onclick=async()=>{try{await api("/api/logout","POST");}finally{csrf=null;$("jobs").replaceChildren();
  $("workspace").hidden=true;$("login").hidden=false;message("");}};
document.addEventListener("visibilitychange",()=>{if(document.hidden)document.querySelectorAll(".secret").forEach(e=>e.remove());});
try {const h=await api("/health");$("environment").textContent=h.environment==="simulator" ?
  "SIMULATOR · Test products and payments only. No real funds move." : (h.environment==="test_merchant" ?
  "CONTROLLED TEST MERCHANT · Actual test-network ZEC only. No redeemable goods or Bitrefill settlement." : "Live discovery only · ZEC settlement is disabled.");
  const s=await api("/api/session");csrf=s.csrf;$("login").hidden=true;$("workspace").hidden=false;await refresh();
}catch{/* Sign-in is the expected initial state. */}
