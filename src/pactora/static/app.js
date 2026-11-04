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
const cents = (c) => money(c) + " test units";
const zat = (z) => new Intl.NumberFormat("en-US").format(z) + " zat";
const when = (t) => new Date(t*1000).toLocaleString();
const labels = {awaiting_approval:"Pending approval",approved:"Approved",expired:"Expired",exhausted:"Exhausted",revoked:"Revoked",completed:"Confirmed",awaiting_test_confirmation:"Awaiting confirmation",reserved:"Pending",attention:"Private attention",requires_private_attention:"Private attention",refused:"Refused",pending:"Checking"};
let data = null, snapshot = "", timer = null, walletLoaded = false;
function clearSecrets() { document.querySelectorAll(".secret").forEach(e=>e.remove()); }
function receiptCard(envelope, title) {
  const card=node("article",undefined,"panel receipt");card.append(node("h3",title));
  const output=node("div");let visible=false;
  card.append(action("Reveal / hide receipt",async()=>{
    visible=!visible;output.replaceChildren();
    if(visible) {
      const result=await reveal(envelope), box=node("div",undefined,"secret");
      box.append(node("p","Private test receipt · payment is separate from usable product delivery"));
      box.append(node("pre",JSON.stringify(result,null,2)));
      output.append(box);
    }
  },true,false),action("Export encrypted receipt",async()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify(envelope)],{type:"application/json"}));
    const a=node("a");a.href=url;a.download="pactora-encrypted-receipt.json";a.click();URL.revokeObjectURL(url);
  },true,false),output);return card;
}
function renderMandate(m) {
  const card=node("article",undefined,"job");const head=node("div",undefined,"jobhead");
  head.append(node("span",labels[m.state]||m.state,"status "+m.state),node("small","INTENT "+m.reference.slice(0,7)+"…","muted"));card.append(head);
  card.append(node("h2",m.products.map(p=>p.name).join(" / "),"intent-title"));
  const d=m.document,u=m.usage||{cents:0,zat:0,count:0},stats=node("div",undefined,"intent-balance");
  [[cents(Math.max(0,d.total_cents-u.cents)),"Accounting budget left"],[zat(Math.max(0,d.total_zat-u.zat)),"Maximum debit left, including fees"],[Math.max(0,d.max_purchases-u.count)+" / "+d.max_purchases,"Purchases remaining"]].forEach(([v,l])=>{const col=node("div");col.append(node("strong",v),node("span",l));stats.append(col);});card.append(stats);
  const progress=node("div",undefined,"usage-bar"),meter=node("meter");meter.min=0;meter.max=d.max_purchases;meter.value=u.count;meter.setAttribute("aria-label","Purchases used");progress.append(meter);card.append(progress);
  const meta=node("div",undefined,"intent-meta");meta.append(node("span",d.merchant+" · "+d.network),node("span","Expires "+when(d.expires_at)));card.append(meta);
  const details=node("details"),summary=node("summary","Review products and spending rules"),dl=node("dl");
  field(dl,"Per purchase",cents(d.per_purchase_cents)+" · "+zat(d.per_purchase_zat));field(dl,"Total limits",cents(d.total_cents)+" · "+zat(d.total_zat));field(dl,"Eligible packages",m.products.map(p=>p.name+" — "+p.package).join("; "));details.append(summary,dl,node("p","No FX quote: dollar figures are test accounting units. The model sees its proposed product; approval, wallet and receipt details remain private.","muted"));card.append(details);
  const buttons=node("div",undefined,"intent-actions");
  if(["awaiting_approval","registration_pending"].includes(m.state))buttons.append(action(m.state==="registration_pending"?"Retry registration":"Approve intent",async()=>{
    const keys=await deviceKeys();await api(`/api/mandates/${m.reference}/approve`,"POST",{draft_hash:m.draft_hash,device_public_key:await publicPem(keys)});
  }));
  if(m.state!=="revoked")buttons.append(action("Revoke intent",()=>api(`/api/mandates/${m.reference}/revoke`,"POST"),true));
  if(m.state!=="awaiting_approval")buttons.append(action("Recover existing payment / receipt",()=>api(`/api/mandates/${m.reference}/recover`,"POST"),true));
  card.append(buttons);
  return card;
}
function renderDelivery(m, purchase, delivery) {
    const box=node("section",undefined,"panel receipt"),dl=node("dl");
    box.append(node("h3","Private delivery · "+delivery.expected.product.name));
    const label=s=>s.replaceAll("_"," ");
    field(dl,"Payment",label(delivery.payment));field(dl,"Fulfillment",label(delivery.fulfillment));
    field(dl,"Private receipt",label(delivery.private_delivery));field(dl,"Refund / review",label(delivery.refund));
    box.append(dl);
    if(delivery.reason)box.append(node("p",label(delivery.reason),"muted"));
    if(delivery.issue)box.append(node("p","Issue reported: "+label(delivery.issue.reason)+". Operator review is required; no refund has been sent or confirmed.","muted"));
    const path=`/api/mandates/${m.reference}/deliveries/${purchase}/action`;
    const envelope=delivery.receipt;
    if(envelope){
      const output=node("div");let visible=false;
      box.append(action("Reveal / hide mandate receipt",async()=>{
        visible=!visible;output.replaceChildren();
        if(visible){
          const receipt=await reveal(envelope);
          output.append(node("pre",JSON.stringify(receipt,null,2),"secret"));
          await api(path,"POST",{action:"accessible"});
          if(delivery.private_delivery!=="acknowledged")delivery.private_delivery="accessible";
          snapshot=JSON.stringify(data);
        }
      },true,false),output);
      box.append(action("I checked this receipt",()=>api(path,"POST",{action:"acknowledged"}),true));
      box.append(action("Export encrypted receipt",async()=>{
        const url=URL.createObjectURL(new Blob([JSON.stringify(envelope)],{type:"application/json"}));
        const a=node("a");a.href=url;a.download="pactora-encrypted-receipt.json";a.click();URL.revokeObjectURL(url);
      },true,false));
    }
    const issue=node("select"),id="issue-"+purchase;
    issue.id=id;const issueLabel=node("label","Report a private delivery issue");issueLabel.htmlFor=id;
    [["missing","Missing delivery"],["invalid","Invalid deliverable"],["partial","Partial delivery"],["device_access","Cannot open private receipt"]].forEach(([value,text])=>{
      const option=node("option",text);option.value=value;issue.append(option);
    });
    box.append(issueLabel,issue,action("Request private review",()=>api(path,"POST",{action:issue.value}),true));
    return box;
}

function empty(title, text) {const el=node("div",undefined,"empty");el.append(node("h2",title),node("p",text));return el;}
function reasonText(d) {
  const reasons={signing_paused:"Signing is paused by you.",product_not_permitted:"This product is outside the approved intent.",mandate_limit_exceeded:"The approved budget or purchase count would be exceeded.",mandate_or_quote_inactive:"The intent or invoice is expired or revoked.",mandate_binding_mismatch:"The merchant or wallet binding does not match.",purchase_reference_changed:"This purchase reference was already bound to a different request.",requires_private_attention:"Review this operation privately. Do not create a replacement payment."};
  if(d.state==="completed")return data.environment==="simulator"?"Simulated purchase. No funds moved.":"Shielded test payment confirmed by the receiver.";
  return reasons[d.reason]||d.reason?.replaceAll("_"," ")||"Checking approved limits.";
}
function renderDecision(d) {
  const row=node("article",undefined,"decision"),request=node("div"),decision=node("div");
  request.append(node("p",d.cents===undefined?"Selection request":cents(d.cents),"amount"),node("p",d.product),node("small","Intent "+d.intent.slice(0,7)+"… · "+when(d.created_at)));
  decision.append(node("span",labels[d.state]||d.state,"status "+d.state),node("p",reasonText(d)));row.append(request,decision);return row;
}
function render() {
  if(!data)return;
  $("mandates").replaceChildren(...data.intents.map(renderMandate));
  if(!data.intents.length)$("mandates").append(empty("No intents yet.","Ask your connected agent to discover a product and request bounded shopping authority."));
  $("jobs").replaceChildren(...data.jobs.map(renderJob));$("legacy").hidden=!data.jobs.length;
  $("decisions").replaceChildren(...data.decisions.map(renderDecision));
  if(!data.decisions.length)$("decisions").append(empty("No payment decisions yet.","Requests and refusals appear here as your agent shops."));
  $("private-receipts").replaceChildren();
  data.intents.forEach(m=>{
    const deliveries=Object.entries(m.deliveries || {});
    deliveries.forEach(([purchase, delivery])=>$("private-receipts").append(renderDelivery(m,purchase,delivery)));
    const tracked=new Set(deliveries.map(([, delivery])=>JSON.stringify(delivery.receipt)).filter(Boolean));
    m.receipts.forEach((e,i)=>{if(!tracked.has(JSON.stringify(e)))$("private-receipts").append(receiptCard(e,"Private receipt · "+m.reference.slice(0,7)+"… / "+(i+1)));});
  });
  $("paused-banner").hidden=!data.paused;$("pause").textContent=data.paused?"▶ Resume signing":"Ⅱ Pause all";
}
async function refresh() {
  if(busy||!csrf||document.hidden)return;busy=true;
  try {
    const next=await api("/api/dashboard"),raw=JSON.stringify(next);data=next;
    if(raw!==snapshot){clearSecrets();snapshot=raw;render();}
    $("connection").textContent="● Live · updates every 2 seconds";
  } catch(e) {$("connection").textContent="● Disconnected · retrying";if(e.message==="sign_in_required")lockLocal();throw e;}
  finally {busy=false;}
}
async function loadWallet() {
  $("wallet-status").replaceChildren(node("p","Checking protected ZecPy service…","muted"));
  try {
    const w=await api("/api/wallet");const box=$("wallet-status");box.replaceChildren(node("h2",w.connected?"Protected wallet connected":"Protected wallet not connected"));
    if(!w.connected){box.append(node("p",data?.environment==="simulator"?"Simulator mode. No real wallet or funds are used.":"The operator must provision the protected wallet service."));return;}
    const figures=node("div",undefined,"wallet-figures");
    [[w.spendable_zat,"Spendable test balance"],[w.pending_zat,"Pending test balance"]].forEach(([v,l])=>{const col=node("div");col.append(node("span",l,"muted"),node("strong",zat(v),"balance-value"));figures.append(col);});box.append(figures);
    const dl=node("dl");field(dl,"Network",w.network);field(dl,"Wallet",w.wallet_id);field(dl,"Signing",w.paused?"Paused":"Available within approved limits");field(dl,"Last synchronized",when(w.last_synced));box.append(dl);
    walletLoaded=true;
  } catch {$("wallet-status").replaceChildren(node("h2","Wallet status unavailable"),node("p","No balance has been inferred. Check the protected service and refresh.","muted"));}
}
function route() {
  clearSecrets();
  const path=location.pathname, landing=path==="/", setup=path==="/setup", privateView=!landing&&!setup;
  $("landing").hidden=!landing;$("setup").hidden=!setup;$("private").hidden=!privateView;
  $("public-nav").hidden=privateView;$("app-nav").hidden=!privateView||!csrf;
  $("launch").hidden=privateView;$("logout").hidden=!privateView||!csrf;$("pause").hidden=!privateView||!csrf;
  $("workspace").hidden=!csrf;$("login").hidden=!!csrf;
  const active=path==="/app/live"?"live":path==="/app/wallet"?"wallet":path==="/app/settings"?"settings":"intents";
  ["intents","live","wallet","settings"].forEach(tab=>{$(tab+"-view").hidden=tab!==active;const link=document.querySelector(`[data-tab="${tab}"]`);if(tab===active)link.setAttribute("aria-current","page");else link.removeAttribute("aria-current");});
  document.title="Pactora · "+(landing?"Private agent commerce":setup?"Connect your agent":active.charAt(0).toUpperCase()+active.slice(1));
  if(privateView&&csrf&&active==="wallet"&&!walletLoaded)loadWallet();
  schedule();
}
function schedule() {clearInterval(timer);timer=null;if(csrf&&!document.hidden&&location.pathname.startsWith("/app"))timer=setInterval(()=>refresh().catch(()=>{}),2000);}
function lockLocal() {csrf=null;data=null;snapshot="";walletLoaded=false;clearSecrets();["jobs","mandates","decisions","private-receipts","wallet-status"].forEach(id=>$(id).replaceChildren());route();}
$("login").onsubmit=async(e)=>{e.preventDefault();message("");try{
  const s=await api("/api/login","POST",{password:$("password").value});$("password").value="";csrf=s.csrf;await refresh();route();
}catch(e){message(e.message);}};
$("refresh").onclick=()=>refresh().catch(e=>message(e.message));
$("wallet-refresh").onclick=()=>loadWallet();
$("logout").onclick=async()=>{try{await api("/api/logout","POST");}finally{lockLocal();message("");}};
$("pause").onclick=async()=>{
  const b=$("pause");b.disabled=true;message("");
  try{await api("/api/control","POST",{paused:!data?.paused});await refresh();}
  catch{message("The signing boundary has not acknowledged the change. New requests are locally paused; check the wallet service.");await refresh().catch(()=>{});}
  finally{b.disabled=false;}
};
document.addEventListener("click",e=>{const a=e.target.closest("a");if(!a||a.origin!==location.origin||a.hash||e.metaKey||e.ctrlKey||e.button)return;if(!["/","/setup","/app","/app/live","/app/wallet","/app/settings"].includes(a.pathname))return;e.preventDefault();history.pushState(null,"",a.pathname);route();window.scrollTo(0,0);});
window.addEventListener("popstate",route);
document.addEventListener("visibilitychange",()=>{clearSecrets();schedule();if(!document.hidden&&csrf)refresh().catch(()=>{});});
route();
try {const h=await api("/health");$("environment").textContent=h.environment==="simulator"?"SIMULATOR · No real funds move. Test products are not redeemable.":h.environment==="test_merchant"?"CONTROLLED TEST MERCHANT · Actual test ZEC. No redeemable goods or Bitrefill settlement.":"BITREFILL DISCOVERY · Live ZEC settlement is disabled.";
  const s=await api("/api/session");csrf=s.csrf;if(location.pathname==="/"){history.replaceState(null,"","/app");}await refresh();route();
}catch{/* An initial sign-in is expected. */}
