//! A thin Varlink client: JSON over a UNIX socket. The only dependency is
//! `serde_json`.
//!
//! A message is one JSON object followed by a NUL byte. A call carries
//! `method` and `parameters`. `more` asks for a stream of replies. In a
//! stream every reply but the last has `"continues": true`. An error reply
//! has `error` and ends the call. One connection carries one call at a time.
//!
//! Passphrases and recovery keys pass through the parameters. This crate
//! never logs them, and `Error`'s `Display` shows only the error name.

use serde_json::{json, Map, Value};
use std::fmt;
use std::io::{self, BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;

pub mod sizes;

#[derive(Debug)]
pub enum Error {
    /// The service answered with an error reply.
    Varlink { name: String, parameters: Value },
    /// The socket failed, or the peer sent something that is not a message.
    Transport(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            // The name only: the parameters can hold a secret.
            Error::Varlink { name, .. } => f.write_str(name),
            Error::Transport(why) => f.write_str(why),
        }
    }
}

impl std::error::Error for Error {}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Transport(e.to_string())
    }
}

pub struct Connection {
    writer: UnixStream,
    reader: BufReader<UnixStream>,
}

impl Connection {
    pub fn connect(path: impl AsRef<Path>) -> Result<Self, Error> {
        let stream = UnixStream::connect(path)?;
        Ok(Self { reader: BufReader::new(stream.try_clone()?), writer: stream })
    }

    fn send(&mut self, request: Value) -> Result<(), Error> {
        let mut wire = serde_json::to_vec(&request).map_err(|e| Error::Transport(e.to_string()))?;
        wire.push(0);
        self.writer.write_all(&wire)?;
        Ok(())
    }

    /// Read one NUL-terminated message. Return (parameters, continues).
    fn receive(&mut self) -> Result<(Value, bool), Error> {
        let mut raw = Vec::new();
        let n = self.reader.read_until(0, &mut raw)?;
        if n == 0 || raw.last() != Some(&0) {
            return Err(Error::Transport("the service closed the connection".into()));
        }
        raw.pop();
        let message: Map<String, Value> = serde_json::from_slice(&raw)
            .map_err(|_| Error::Transport("a message is not a JSON object".into()))?;
        let parameters = message.get("parameters").cloned().unwrap_or_else(|| json!({}));
        if let Some(name) = message.get("error").and_then(Value::as_str) {
            return Err(Error::Varlink { name: name.to_string(), parameters });
        }
        let continues = message.get("continues").and_then(Value::as_bool).unwrap_or(false);
        Ok((parameters, continues))
    }

    /// A call with one reply.
    pub fn call(&mut self, method: &str, parameters: Value) -> Result<Value, Error> {
        self.send(json!({ "method": method, "parameters": parameters }))?;
        Ok(self.receive()?.0)
    }

    /// A streaming call. `on_reply` runs for each reply, the last one
    /// included. The last reply can have empty parameters. Return `false`
    /// to stop early, and drop the connection after that.
    pub fn call_more(
        &mut self,
        method: &str,
        parameters: Value,
        mut on_reply: impl FnMut(Value) -> bool,
    ) -> Result<(), Error> {
        self.send(json!({ "method": method, "parameters": parameters, "more": true }))?;
        loop {
            let (reply, continues) = self.receive()?;
            if !on_reply(reply) || !continues {
                return Ok(());
            }
        }
    }

    /// A call that gets no reply.
    pub fn call_oneway(&mut self, method: &str, parameters: Value) -> Result<(), Error> {
        self.send(json!({ "method": method, "parameters": parameters, "oneway": true }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    use std::os::unix::net::UnixListener;
    use std::thread;

    /// A peer that sends `script` bytes after the first request. It is a test
    /// double for the wire format, not the mock daemon.
    fn peer(name: &str, script: Vec<Vec<u8>>) -> (std::path::PathBuf, thread::JoinHandle<Vec<u8>>) {
        let dir = std::env::temp_dir().join(format!("vl-{}-{}", std::process::id(), name));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("s");
        let _ = std::fs::remove_file(&path);
        let listener = UnixListener::bind(&path).unwrap();
        let handle = thread::spawn(move || {
            let (mut conn, _) = listener.accept().unwrap();
            let mut request = Vec::new();
            let mut byte = [0u8; 1];
            while conn.read(&mut byte).unwrap() == 1 {
                request.push(byte[0]);
                if byte[0] == 0 {
                    break;
                }
            }
            for part in script {
                conn.write_all(&part).unwrap();
                conn.flush().unwrap();
                thread::sleep(std::time::Duration::from_millis(10));
            }
            request
        });
        (path, handle)
    }

    #[test]
    fn a_stream_ends_on_the_reply_without_continues() {
        let (path, peer) = peer(
            "stream",
            vec![
                b"{\"parameters\":{\"progress\":10},\"continues\":true}\0{\"parameters\":{\"prog".to_vec(),
                b"ress\":100},\"continues\":true}\0".to_vec(),
                b"{\"parameters\":{}}\0".to_vec(),
            ],
        );
        let mut c = Connection::connect(&path).unwrap();
        let mut seen = Vec::new();
        c.call_more("io.systemd.SysInstall.Run", json!({"node": "/dev/vda"}), |p| {
            seen.push(p.get("progress").and_then(Value::as_i64));
            true
        })
        .unwrap();
        assert_eq!(seen, vec![Some(10), Some(100), None]);
        let request = peer.join().unwrap();
        assert_eq!(request.last(), Some(&0));
        let sent: Value = serde_json::from_slice(&request[..request.len() - 1]).unwrap();
        assert_eq!(sent["more"], json!(true));
    }

    #[test]
    fn an_error_reply_keeps_its_name_and_hides_its_parameters() {
        let (path, peer) = peer(
            "error",
            vec![b"{\"error\":\"io.systemd.SysInstall.DiskTooSmall\",\"parameters\":{\"passphrase\":\"hunter2\"}}\0".to_vec()],
        );
        let mut c = Connection::connect(&path).unwrap();
        let err = c.call("io.systemd.SysInstall.Run", json!({})).unwrap_err();
        assert_eq!(err.to_string(), "io.systemd.SysInstall.DiskTooSmall");
        assert!(!format!("{err}").contains("hunter2"));
        peer.join().unwrap();
    }

    #[test]
    fn a_closed_connection_is_a_transport_error() {
        let (path, peer) = peer("closed", vec![]);
        let mut c = Connection::connect(&path).unwrap();
        assert!(matches!(c.call("x.Y", json!({})), Err(Error::Transport(_))));
        peer.join().unwrap();
    }

    #[test]
    fn the_size_fixtures_hold() {
        let raw = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../fixtures/sizes.json")).unwrap();
        let doc: Value = serde_json::from_str(&raw).unwrap();
        let cases = doc["cases"].as_array().unwrap();
        assert!(cases.len() > 10);
        for case in cases {
            let input = case["input"].as_str().unwrap();
            assert_eq!(sizes::normalize_size_text(input), case["normalized"].as_str().unwrap(), "{}", case["name"]);
            assert_eq!(sizes::parse_size(input), case["bytes"].as_i64(), "{}", case["name"]);
        }
    }
}
