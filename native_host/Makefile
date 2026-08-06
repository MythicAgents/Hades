# Build Hades native TCP relay host.
# PSK and ExtID are injected at link time — no placeholder substitution needed.
#
# Usage:
#   make all PSK=<32-char-hex> EXT_ID=<32-char-extension-id>
#
# Called by the Mythic builder (hades.py) with the correct values automatically.
# Run `make all` with dummy values for testing.

PSK    ?= 0000000000000000000000000000000000000000000000000000000000000000
EXT_ID ?= aaaabbbbccccddddeeeeffffaaaabbbb

BINARY := hades_socks5_host
FLAGS  := -ldflags="-s -w -X main.PSK=$(PSK) -X main.ExtID=$(EXT_ID)" -trimpath
OUTDIR := bin

.PHONY: all clean deps macos-arm64 macos-amd64 linux-amd64 windows-amd64

all: deps macos-arm64 macos-amd64 linux-amd64 windows-amd64
	@echo "Built in $(OUTDIR)/"

deps:
	go mod tidy

$(OUTDIR):
	mkdir -p $(OUTDIR)

macos-arm64: $(OUTDIR)
	GOOS=darwin  GOARCH=arm64 go build $(FLAGS) -o $(OUTDIR)/$(BINARY)_macos_arm64       .

macos-amd64: $(OUTDIR)
	GOOS=darwin  GOARCH=amd64 go build $(FLAGS) -o $(OUTDIR)/$(BINARY)_macos_amd64       .

linux-amd64: $(OUTDIR)
	GOOS=linux   GOARCH=amd64 go build $(FLAGS) -o $(OUTDIR)/$(BINARY)_linux_amd64        .

windows-amd64: $(OUTDIR)
	GOOS=windows GOARCH=amd64 go build $(FLAGS) -o $(OUTDIR)/$(BINARY)_windows_amd64.exe .

clean:
	rm -rf $(OUTDIR)/
