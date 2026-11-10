// The recovery key stays out of the install log (#337).
//
// fisherman sends the LUKS recovery key once, in a `recovery_key` event on
// stdout. The done page shows it and holds Restart until the user says that
// it is saved. install.log outlives the window, and a user attaches it to a
// bug report, so it gets the redacted form: the event type stays, the key's
// value becomes "[redacted]". The form is the same in every frontend that
// keeps a log, byte for byte: ../../../shared/progress/recovery-key-cases.json.

package main

import (
	"bytes"
	"encoding/json"
	"io"
	"regexp"
	"strings"
	"sync"
)

// redactedKey is what replaces a key.
const redactedKey = "[redacted]"

var (
	// {"type":"recovery_key","key":"..."}: the value, with its escapes.
	reKeyEvent = regexp.MustCompile(`("key"\s*:\s*")(?:[^"\\]|\\.)*(")`)
	// The line a frontend renders for that event.
	reKeyLine = regexp.MustCompile(`(Recovery key:\s*)\S.*`)
)

// redactRecoveryKey is `text` (one line or many) without a recovery key.
// Three forms go: the `key` value of a `recovery_key` event, the text after
// "Recovery key:", and knownKey wherever a later line repeats it.
func redactRecoveryKey(text, knownKey string) string {
	if text == "" {
		return text
	}
	lines := strings.Split(text, "\n")
	for i, line := range lines {
		if strings.Contains(line, `"recovery_key"`) {
			line = reKeyEvent.ReplaceAllString(line, "${1}"+redactedKey+"${2}")
		}
		lines[i] = reKeyLine.ReplaceAllString(line, "${1}"+redactedKey)
	}
	out := strings.Join(lines, "\n")
	if known := strings.TrimSpace(knownKey); known != "" {
		out = strings.ReplaceAll(out, known, redactedKey)
	}
	return out
}

// redactedLog writes fisherman's two streams to one log file, a whole line
// at a time and without the recovery key. Each stream keeps its own partial
// line, so a line split across two reads is redacted whole. The key that a
// recovery_key event names is remembered, so a later line on either stream
// that repeats it is redacted too.
type redactedLog struct {
	mu  sync.Mutex
	out io.Writer
	key string
}

func newRedactedLog(out io.Writer) *redactedLog { return &redactedLog{out: out} }

// Stream is an io.Writer for one of fisherman's streams.
func (l *redactedLog) Stream() *redactedStream { return &redactedStream{log: l} }

type redactedStream struct {
	log *redactedLog
	buf []byte
}

func (s *redactedStream) Write(p []byte) (int, error) {
	s.buf = append(s.buf, p...)
	for {
		nl := bytes.IndexByte(s.buf, '\n')
		if nl < 0 {
			return len(p), nil
		}
		line := string(s.buf[:nl])
		s.buf = s.buf[nl+1:]
		if err := s.log.writeLine(line); err != nil {
			return len(p), err
		}
	}
}

// Flush writes a last line that has no newline.
func (s *redactedStream) Flush() error {
	if len(s.buf) == 0 {
		return nil
	}
	line := string(s.buf)
	s.buf = nil
	return s.log.writeLine(line)
}

func (l *redactedLog) writeLine(line string) error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if strings.Contains(line, `"recovery_key"`) {
		var event struct {
			Type string `json:"type"`
			Key  string `json:"key"`
		}
		if json.Unmarshal([]byte(line), &event) == nil && event.Type == "recovery_key" && event.Key != "" {
			l.key = event.Key
		}
	}
	_, err := io.WriteString(l.out, redactRecoveryKey(line, l.key)+"\n")
	return err
}
