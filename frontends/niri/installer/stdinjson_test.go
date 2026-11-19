package main

import (
	"io"
	"testing"
	"time"
)

// Quickshell writes the request and keeps stdin open. The read must finish
// without EOF. Falsification: with io.ReadAll this test times out.
func TestReadOneJSONDoesNotWaitForEOF(t *testing.T) {
	r, w := io.Pipe()
	defer w.Close()
	go func() { _, _ = w.Write([]byte(`{"disk":"/dev/vda","user":{"name":"tunaose2e"}}` + "\n")) }()
	done := make(chan []byte, 1)
	go func() {
		got, err := readOneJSON(r, 1<<20)
		if err != nil {
			t.Errorf("readOneJSON: %v", err)
		}
		done <- got
	}()
	select {
	case got := <-done:
		if string(got) != `{"disk":"/dev/vda","user":{"name":"tunaose2e"}}` {
			t.Fatalf("got %q", got)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("readOneJSON waited for EOF on an open stdin")
	}
}

func TestReadOneJSONRejectsEmptyAndGarbage(t *testing.T) {
	if _, err := readOneJSON(emptyReader{}, 10); err == nil {
		t.Fatal("empty stdin accepted")
	}
	if _, err := readOneJSON(stringReader("not json"), 100); err == nil {
		t.Fatal("garbage accepted")
	}
}

type emptyReader struct{}

func (emptyReader) Read([]byte) (int, error) { return 0, io.EOF }

type stringReader string

func (s stringReader) Read(p []byte) (int, error) { n := copy(p, s); return n, io.EOF }
