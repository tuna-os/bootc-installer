package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

// readOneJSON reads a single JSON value from r and returns its bytes. It does
// not wait for EOF.
//
// Quickshell's Process.write() sends the request but leaves the child's stdin
// open, so io.ReadAll blocked forever: on marlin-niri (tunaOS strict run
// iso-builder 43918492443) `validate`, `plan` and `install` were all still
// alive minutes after the request, the install page stayed on "Starting...",
// and fisherman was never run. One JSON document is the whole request, so the
// decoder stops at its end.
func readOneJSON(r io.Reader, limit int64) ([]byte, error) {
	var raw json.RawMessage
	dec := json.NewDecoder(io.LimitReader(r, limit))
	if err := dec.Decode(&raw); err != nil {
		if errors.Is(err, io.EOF) {
			return nil, errors.New("no request on stdin")
		}
		return nil, fmt.Errorf("request on stdin is not JSON: %w", err)
	}
	return raw, nil
}
