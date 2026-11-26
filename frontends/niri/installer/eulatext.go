package main

// The eula page shows the terms as text. The shared file is an AppStream
// component with an agreement of type eula (KDE's eula.cpp reads it the
// same way); a file that is not XML is taken as plain text.

import (
	"encoding/xml"
	"errors"
	"io"
	"strconv"
	"strings"
)

// eulaPlainText returns the terms of an AppStream eula agreement as
// plain text: each section's name, its paragraphs, list items as bullets.
// A file that does not start with "<" is returned as it is. XML with no
// eula agreement is an error: nothing in it is terms of use.
func eulaPlainText(data []byte) (string, error) {
	text := string(data)
	if !strings.HasPrefix(strings.TrimSpace(text), "<") {
		return strings.TrimSpace(text), nil
	}
	dec := xml.NewDecoder(strings.NewReader(text))
	var (
		out          []string
		inAgreement  bool
		found        bool
		depth        int // depth inside the eula agreement
		cur          strings.Builder
		capturing    string // "name", "p" or "li"
		listOrdinal  int
		orderedLists []bool
	)
	for {
		tok, err := dec.Token()
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			return "", err
		}
		switch t := tok.(type) {
		case xml.StartElement:
			if !inAgreement {
				if t.Name.Local == "agreement" {
					for _, a := range t.Attr {
						if a.Name.Local == "type" && a.Value == "eula" {
							inAgreement, found, depth = true, true, 0
						}
					}
				}
				continue
			}
			depth++
			switch t.Name.Local {
			case "name", "p", "li":
				if capturing == "" {
					capturing = t.Name.Local
					cur.Reset()
				}
			case "ol", "ul":
				orderedLists = append(orderedLists, t.Name.Local == "ol")
				listOrdinal = 0
			}
		case xml.EndElement:
			if !inAgreement {
				continue
			}
			if depth == 0 && t.Name.Local == "agreement" {
				inAgreement = false
				continue
			}
			depth--
			if t.Name.Local == capturing {
				s := strings.Join(strings.Fields(cur.String()), " ")
				if s != "" {
					switch capturing {
					case "li":
						listOrdinal++
						if len(orderedLists) > 0 && orderedLists[len(orderedLists)-1] {
							s = strings.Repeat(" ", 2) + strconv.Itoa(listOrdinal) + ". " + s
						} else {
							s = "  • " + s
						}
					}
					out = append(out, s)
				}
				capturing = ""
			}
			if (t.Name.Local == "ol" || t.Name.Local == "ul") && len(orderedLists) > 0 {
				orderedLists = orderedLists[:len(orderedLists)-1]
			}
		case xml.CharData:
			if capturing != "" {
				cur.Write(t)
			}
		}
	}
	if !found {
		return "", errors.New("no eula agreement")
	}
	// Paragraphs and names are separated by a blank line; list items by one
	// line break.
	var b strings.Builder
	for i, s := range out {
		if i > 0 {
			if strings.HasPrefix(s, "  ") && strings.HasPrefix(out[i-1], "  ") {
				b.WriteString("\n")
			} else {
				b.WriteString("\n\n")
			}
		}
		b.WriteString(s)
	}
	return b.String(), nil
}
