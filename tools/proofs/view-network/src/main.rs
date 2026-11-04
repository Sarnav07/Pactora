//! Test-harness helper: re-encode public address / confidential viewing material
//! for private regtest without implementing cryptography or altering key material.
use std::{env, fs};
use zcash_address::unified::{Address, Encoding, Ufvk};
use zcash_protocol::consensus::NetworkType;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        return Err("usage: view-network address|ufvk INPUT OUTPUT".into());
    }
    let input = fs::read_to_string(&args[2])?;
    let output = match args[1].as_str() {
        "address" => {
            let (_, _, value) = Address::decode(input.trim())?;
            value.encode(&NetworkType::Regtest)
        }
        "ufvk" => {
            let (_, _, value) = Ufvk::decode(input.trim())?;
            value.encode(&NetworkType::Regtest)
        }
        _ => return Err("only address or ufvk is supported".into()),
    };
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    use std::io::Write;
    options.open(&args[3])?.write_all(output.as_bytes())?;
    Ok(())
}
