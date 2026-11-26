// Vendored from shared/client/go/varlink.go (tuna-os/installer#442).
// Kept in sync by hand: the daemon interface is stable, and a module
// dependency would drag the whole shared tree into the Flatpak.
// Package varlink is a thin Varlink client: JSON over a UNIX socket, with
// only the standard library.
//
// A message is one JSON object followed by a NUL byte. A call carries
// "method" and "parameters". "more" asks for a stream of replies. In a
// stream every reply but the last has "continues": true. An error reply has
// "error" and ends the call. One connection carries one call at a time.
//
// Passphrases and recovery keys pass through the parameters. This package
// never logs them, and Error.Error() returns only the error name.
package varlink

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"time"
)

// Error is an error reply from the service.
type Error struct {
	Name       string
	Parameters json.RawMessage
}

// Error returns the error name only, because the parameters can hold a secret.
func (e *Error) Error() string { return e.Name }

// Conn is one connection to a service socket.
type Conn struct {
	c net.Conn
	r *bufio.Reader
}

// Dial connects to the UNIX socket at path.
func Dial(path string, timeout time.Duration) (*Conn, error) {
	c, err := net.DialTimeout("unix", path, timeout)
	if err != nil {
		return nil, err
	}
	return &Conn{c: c, r: bufio.NewReader(c)}, nil
}

// NewConn wraps an existing connection. Tests use it with net.Pipe.
func NewConn(c net.Conn) *Conn { return &Conn{c: c, r: bufio.NewReader(c)} }

// Close closes the connection.
func (c *Conn) Close() error { return c.c.Close() }

type request struct {
	Method     string      `json:"method"`
	Parameters interface{} `json:"parameters"`
	More       bool        `json:"more,omitempty"`
	Oneway     bool        `json:"oneway,omitempty"`
}

type reply struct {
	Parameters json.RawMessage `json:"parameters"`
	Continues  bool            `json:"continues"`
	Error      string          `json:"error"`
}

func (c *Conn) send(req request) error {
	if req.Parameters == nil {
		req.Parameters = struct{}{}
	}
	b, err := json.Marshal(req)
	if err != nil {
		return err
	}
	_, err = c.c.Write(append(b, 0))
	return err
}

// receive reads one NUL-terminated message.
func (c *Conn) receive() (*reply, error) {
	raw, err := c.r.ReadBytes(0)
	if err != nil {
		if errors.Is(err, io.EOF) {
			return nil, errors.New("varlink: the service closed the connection")
		}
		return nil, err
	}
	var r reply
	if err := json.Unmarshal(raw[:len(raw)-1], &r); err != nil {
		return nil, fmt.Errorf("varlink: a message is not JSON: %w", err)
	}
	if r.Error != "" {
		return nil, &Error{Name: r.Error, Parameters: r.Parameters}
	}
	return &r, nil
}

// Call makes a call with one reply and decodes its parameters into out.
// out can be nil.
func (c *Conn) Call(method string, params, out interface{}) error {
	if err := c.send(request{Method: method, Parameters: params}); err != nil {
		return err
	}
	r, err := c.receive()
	if err != nil {
		return err
	}
	return decode(r.Parameters, out)
}

// CallMore makes a streaming call. It calls fn with the parameters of each
// reply, the last one included. The last reply can have empty parameters.
// fn returns false to stop early: close the connection after that.
func (c *Conn) CallMore(method string, params interface{}, fn func(json.RawMessage) bool) error {
	if err := c.send(request{Method: method, Parameters: params, More: true}); err != nil {
		return err
	}
	for {
		r, err := c.receive()
		if err != nil {
			return err
		}
		if !fn(r.Parameters) {
			return nil
		}
		if !r.Continues {
			return nil
		}
	}
}

// CallOneway makes a call and does not wait for a reply.
func (c *Conn) CallOneway(method string, params interface{}) error {
	return c.send(request{Method: method, Parameters: params, Oneway: true})
}

func decode(p json.RawMessage, out interface{}) error {
	if out == nil || len(p) == 0 {
		return nil
	}
	return json.Unmarshal(p, out)
}

// Decode decodes the parameters of one reply of a stream into out.
func Decode(p json.RawMessage, out interface{}) error { return decode(p, out) }
