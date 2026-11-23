use std::io::{self, BufRead, Read, Write};

use candlescope_plugin_sdk::{parse_json, ProtocolError, Value, MAX_MESSAGE_BYTES};

// The old adapter is covered by a release source lock. Reuse its search
// implementation and tests without changing that reviewed source or calling
// its Platform v2 server.
#[allow(dead_code)]
mod reference {
    pub(super) fn run_search(input: &Value) -> Result<Value, ProtocolError> {
        search(input)
    }

    include!("../../../plugins/aho-corasick-adapter/src/main.rs");
}

const PROTOCOL: &str = "candlescope.unified-entry/1";
const PLUGIN_ID: &str = "candlescope.aho-corasick";
const ENTRY_ID: &str = "main";

fn fields(value: &Value, expected: &[&str]) -> Result<(), ProtocolError> {
    let object = value.as_object()?;
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err(ProtocolError::invalid("unexpected object fields"));
    }
    Ok(())
}

fn lower_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

#[derive(Default)]
struct Entry {
    generation: Option<u64>,
}

impl Entry {
    fn activate(&mut self, generation: u64, params: &Value) -> Result<Value, ProtocolError> {
        fields(params, &["protocol", "identity", "storage"])?;
        let identity = params.field("identity")?;
        fields(
            identity,
            &[
                "pluginId",
                "version",
                "packageSha256",
                "generation",
                "entryId",
                "instanceId",
            ],
        )?;
        let digest = identity.field("packageSha256")?.as_str()?;
        if self.generation.is_some()
            || params.field("protocol")?.as_str()? != PROTOCOL
            || params.field("storage")?.as_str()?.is_empty()
            || generation == 0
            || identity.field("generation")?.as_u64()? != generation
            || identity.field("pluginId")?.as_str()? != PLUGIN_ID
            || identity.field("version")?.as_str()? != env!("CARGO_PKG_VERSION")
            || identity.field("entryId")?.as_str()? != ENTRY_ID
            || !lower_hex(identity.field("instanceId")?.as_str()?, 32)
            || !digest
                .strip_prefix("sha256:")
                .is_some_and(|hex| lower_hex(hex, 64))
        {
            return Err(ProtocolError::invalid(
                "unified activation identity is invalid",
            ));
        }
        self.generation = Some(generation);
        Ok(Value::object([
            ("protocol", Value::from(PROTOCOL)),
            ("identity", identity.clone()),
        ]))
    }

    fn invoke(
        &mut self,
        generation: u64,
        method: &str,
        params: &Value,
    ) -> Result<Value, ProtocolError> {
        match method {
            "activate" => self.activate(generation, params),
            "invoke" => {
                if self.generation != Some(generation) {
                    return Err(ProtocolError::new(
                        -32000,
                        "UNIFIED_ENTRY_NOT_CURRENT",
                        "search requires the current activation generation",
                    ));
                }
                fields(params, &["input"])?;
                reference::run_search(params.field("input")?)
            }
            _ => Err(ProtocolError::new(
                -32601,
                "METHOD_NOT_FOUND",
                "unsupported unified entry method",
            )),
        }
    }

    fn respond(&mut self, request: &Value) -> Result<Value, ProtocolError> {
        let id = request.field("id")?.as_str()?;
        let generation = request.field("generation")?.as_u64()?;
        if id.is_empty() || id.len() > 128 {
            return Err(ProtocolError::invalid("invalid request id"));
        }
        let response = (|| {
            fields(
                request,
                &["jsonrpc", "id", "generation", "method", "params"],
            )?;
            if request.field("jsonrpc")?.as_str()? != "2.0" {
                return Err(ProtocolError::invalid("expected JSON-RPC 2.0"));
            }
            self.invoke(
                generation,
                request.field("method")?.as_str()?,
                request.field("params")?,
            )
        })();
        let (key, body) = match response {
            Ok(result) => ("result", result),
            Err(error) => (
                "error",
                Value::object([
                    ("code", Value::integer(error.rpc_code)),
                    ("message", Value::from(error.message)),
                    ("data", Value::object([("code", Value::from(error.code))])),
                ]),
            ),
        };
        Ok(Value::object([
            ("id", Value::from(id)),
            ("generation", Value::unsigned(generation)),
            ("jsonrpc", Value::from("2.0")),
            (key, body),
        ]))
    }
}

fn serve(
    mut input: impl BufRead,
    mut output: impl Write,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut entry = Entry::default();
    let mut frame = Vec::new();
    loop {
        frame.clear();
        if (&mut input)
            .take((MAX_MESSAGE_BYTES + 2) as u64)
            .read_until(b'\n', &mut frame)?
            == 0
        {
            return Ok(());
        }
        let body = frame
            .strip_suffix(b"\n")
            .ok_or("incomplete or oversized JSONL frame")?;
        let body = body.strip_suffix(b"\r").unwrap_or(body);
        let request = parse_json(std::str::from_utf8(body)?)?;
        let response = entry.respond(&request)?.to_canonical_json();
        if response.len() > MAX_MESSAGE_BYTES {
            return Err("response exceeds the JSONL budget".into());
        }
        writeln!(output, "{response}")?;
        output.flush()?;
    }
}

fn main() {
    if let Err(error) = serve(io::stdin().lock(), io::BufWriter::new(io::stdout().lock())) {
        eprintln!("aho-corasick unified entry failed: {error}");
        std::process::exit(2);
    }
}
