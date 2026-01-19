.PHONY: build install clean run dev

# Binary name
BINARY=voice-synth-tui

# Build the Go binary
build:
	go mod tidy
	go build -o $(BINARY) .

# Build for multiple platforms
build-all:
	GOOS=darwin GOARCH=amd64 go build -o $(BINARY)-darwin-amd64 .
	GOOS=darwin GOARCH=arm64 go build -o $(BINARY)-darwin-arm64 .
	GOOS=linux GOARCH=amd64 go build -o $(BINARY)-linux-amd64 .

# Install locally
install: build
	mv $(BINARY) /usr/local/bin/

# Run in development mode
dev:
	go run .

# Clean build artifacts
clean:
	rm -f $(BINARY) $(BINARY)-*
	go clean

# Run tests
test:
	go test ./...
