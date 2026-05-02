// snappy_codec — tiny CLI to decompress/compress raw snappy. We use this
// because the runner harnesses need to feed plain SSZ to clients whose
// CLIs don't accept .ssz_snappy directly (lcli, teku).
//
// Usage:
//   snappy_codec d <in.snappy> <out.bin>     # decompress
//   snappy_codec e <in.bin>    <out.snappy>  # compress
//   snappy_codec sha256 <in.snappy>          # decompress and print sha256
package main

import (
	"crypto/sha256"
	"fmt"
	"os"

	"github.com/golang/snappy"
)

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintln(os.Stderr, "usage: snappy_codec {d|e|sha256} <in> [out]")
		os.Exit(2)
	}
	mode := os.Args[1]
	in, err := os.ReadFile(os.Args[2])
	if err != nil {
		fmt.Fprintln(os.Stderr, "read:", err)
		os.Exit(1)
	}
	switch mode {
	case "d":
		out, err := snappy.Decode(nil, in)
		if err != nil {
			fmt.Fprintln(os.Stderr, "decode:", err)
			os.Exit(1)
		}
		if err := os.WriteFile(os.Args[3], out, 0o644); err != nil {
			fmt.Fprintln(os.Stderr, "write:", err)
			os.Exit(1)
		}
	case "e":
		out := snappy.Encode(nil, in)
		if err := os.WriteFile(os.Args[3], out, 0o644); err != nil {
			fmt.Fprintln(os.Stderr, "write:", err)
			os.Exit(1)
		}
	case "sha256":
		out, err := snappy.Decode(nil, in)
		if err != nil {
			fmt.Fprintln(os.Stderr, "decode:", err)
			os.Exit(1)
		}
		sum := sha256.Sum256(out)
		fmt.Printf("%x\n", sum)
	default:
		fmt.Fprintln(os.Stderr, "unknown mode:", mode)
		os.Exit(2)
	}
}
