package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/progress"
	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// Global program reference for sending messages from goroutines
var program *tea.Program

const version = "0.5.1-alpha"

// Colors matching the purple/green aesthetic
var (
	purple    = lipgloss.Color("#9370DB")
	green     = lipgloss.Color("#00FF7F")
	dim       = lipgloss.Color("#666666")
	white     = lipgloss.Color("#FFFFFF")
	red       = lipgloss.Color("#FF6B6B")
	yellow    = lipgloss.Color("#FFD93D")

	titleStyle = lipgloss.NewStyle().
			Foreground(purple).
			Bold(true).
			MarginBottom(1)

	subtitleStyle = lipgloss.NewStyle().
			Foreground(dim).
			MarginBottom(1)

	menuStyle = lipgloss.NewStyle().
			Border(lipgloss.DoubleBorder()).
			BorderForeground(purple).
			Padding(1, 3).
			Width(50)

	selectedStyle = lipgloss.NewStyle().
			Foreground(green).
			Bold(true)

	normalStyle = lipgloss.NewStyle().
			Foreground(white)

	errorStyle = lipgloss.NewStyle().
			Foreground(red)

	successStyle = lipgloss.NewStyle().
			Foreground(green)

	dimStyle = lipgloss.NewStyle().
			Foreground(dim)

	stageCompleteStyle = lipgloss.NewStyle().
				Foreground(green)

	stageRunningStyle = lipgloss.NewStyle().
				Foreground(yellow)

	stagePendingStyle = lipgloss.NewStyle().
				Foreground(dim)
)

// Screen types
type screen int

const (
	screenMainMenu screen = iota
	screenFilePicker
	screenSenderFilter
	screenProgress
	screenResults
	screenHelp
	screenUninstall
	screenSetup
)

// Pipeline stages
type stage int

const (
	stageImport stage = iota
	stageConvert
	stageClean
	stageCurate
	stageDone
)

// Messages
type (
	setupNextMsg        struct{ step int }
	setupCompleteMsg    struct{}
	setupErrorMsg       struct{ err error }
	stageCompleteMsg    struct{ stage stage; stats map[string]int }
	stageErrorMsg       struct{ stage stage; err error }
	pipelineCompleteMsg struct{ results map[string]map[string]int }
	ownerDetectedMsg    struct{ email string }
	logUpdateMsg        struct{ line string }
	tickMsg             time.Time
)

// Model
type model struct {
	screen       screen
	menuCursor   int
	menuItems    []string
	textInput    textinput.Model
	spinner      spinner.Model
	progress     progress.Model

	// Pipeline state
	inputFile    string
	sender       string
	workDir      string
	currentStage stage
	stageStats   map[stage]map[string]int
	results      map[string]map[string]int
	failedStage  stage    // -1 if no failure
	logLines     []string // Rolling log output

	// Setup state
	setupStep       int
	setupSteps      []string
	setupDone       bool

	// Status message (for various screens)
	statusMsg    string

	// Resume state
	incompleteJob *Job

	// Error state
	errMsg       string

	// Screen dimensions
	width        int
	height       int
}

func initialModel() model {
	ti := textinput.New()
	ti.Placeholder = "Drag file here or type path..."
	ti.Focus()
	ti.Width = 40

	s := spinner.New()
	s.Spinner = spinner.Dot
	s.Style = lipgloss.NewStyle().Foreground(purple)

	p := progress.New(progress.WithDefaultGradient())

	return model{
		screen:      screenSetup,
		menuItems:   []string{"Get Started", "Help", "Uninstall", "Quit"},
		textInput:   ti,
		spinner:     s,
		progress:    p,
		stageStats:  make(map[stage]map[string]int),
		failedStage: -1,
		setupStep:   -1,
		setupSteps:  []string{
			"Creating Python environment",
			"Installing core libraries",
			"Installing Presidio (PII detection)",
			"Installing spaCy (NLP)",
			"Downloading language model (~500MB)",
		},
	}
}

func (m model) Init() tea.Cmd {
	return tea.Batch(
		m.spinner.Tick,
		checkPythonSetup,
	)
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		// On screens with text input, let textInput handle most keys
		if m.screen == screenFilePicker || m.screen == screenSenderFilter || m.screen == screenUninstall {
			switch msg.String() {
			case "ctrl+c":
				return m, tea.Quit
			case "esc":
				m.screen = screenMainMenu
				m.errMsg = ""
				m.textInput.SetValue("")
				return m, nil
			case "enter":
				return m.handleEnter()
			default:
				// Pass all other keys to text input
				var cmd tea.Cmd
				m.textInput, cmd = m.textInput.Update(msg)
				return m, cmd
			}
		}
		return m.handleKeyPress(msg)

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		return m, cmd

	case tickMsg:
		return m, tea.Tick(100*time.Millisecond, func(t time.Time) tea.Msg {
			return tickMsg(t)
		})

	case setupNextMsg:
		m.setupStep = msg.step
		return m, runSetupStep(msg.step)

	case setupCompleteMsg:
		m.setupDone = true
		m.screen = screenMainMenu
		// Check for incomplete job
		m.incompleteJob = getIncompleteJob()
		if m.incompleteJob != nil {
			m.menuItems = []string{"Resume previous", "Get Started", "Help", "Uninstall", "Quit"}
		}
		return m, nil

	case setupErrorMsg:
		m.errMsg = msg.err.Error()
		return m, nil

	case ownerDetectedMsg:
		m.textInput.SetValue(msg.email)
		m.statusMsg = fmt.Sprintf("Detected: %s", msg.email)
		return m, nil

	case logUpdateMsg:
		// Add line to rolling log (keep last 8 lines)
		m.logLines = append(m.logLines, msg.line)
		if len(m.logLines) > 8 {
			m.logLines = m.logLines[len(m.logLines)-8:]
		}
		return m, nil

	case stageCompleteMsg:
		m.stageStats[msg.stage] = msg.stats
		m.currentStage = msg.stage + 1
		m.logLines = nil // Clear log for next stage
		if m.currentStage < stageDone {
			return m, runPipelineStage(m.inputFile, m.sender, m.workDir, m.currentStage)
		}
		return m, nil

	case stageErrorMsg:
		m.failedStage = msg.stage
		m.errMsg = msg.err.Error()
		return m, nil

	case pipelineCompleteMsg:
		m.results = msg.results
		m.screen = screenResults
		// Mark job as complete
		markJobComplete(m.workDir)
		return m, nil
	}

	return m, nil
}

func (m model) handleKeyPress(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c", "q":
		if m.screen == screenMainMenu || m.screen == screenResults {
			return m, tea.Quit
		}
		// Go back to main menu
		m.screen = screenMainMenu
		m.errMsg = ""
		return m, nil

	case "esc":
		if m.screen != screenMainMenu && m.screen != screenProgress {
			m.screen = screenMainMenu
			m.errMsg = ""
		}
		return m, nil

	case "up", "k":
		if m.screen == screenMainMenu && m.menuCursor > 0 {
			m.menuCursor--
		}
		return m, nil

	case "down", "j":
		if m.screen == screenMainMenu && m.menuCursor < len(m.menuItems)-1 {
			m.menuCursor++
		}
		return m, nil

	case "enter":
		return m.handleEnter()
	}

	return m, nil
}

func (m model) handleEnter() (tea.Model, tea.Cmd) {
	switch m.screen {
	case screenMainMenu:
		switch m.menuItems[m.menuCursor] {
		case "Resume previous":
			if m.incompleteJob != nil {
				m.inputFile = m.incompleteJob.Mbox
				m.sender = m.incompleteJob.Sender
				m.workDir = m.incompleteJob.WorkDir
				m.screen = screenProgress
				m.errMsg = ""
				// Determine which stage to resume from
				resumeStage := stageImport
				if _, err := os.Stat(filepath.Join(m.workDir, "cleaned_emails.json")); err == nil {
					resumeStage = stageCurate
					// Mark prior stages as complete
					m.stageStats[stageImport] = map[string]int{"resumed": 1}
					m.stageStats[stageConvert] = map[string]int{"resumed": 1}
					m.stageStats[stageClean] = map[string]int{"resumed": 1}
				} else if _, err := os.Stat(filepath.Join(m.workDir, "emails.jsonl")); err == nil {
					resumeStage = stageClean
					m.stageStats[stageImport] = map[string]int{"resumed": 1}
					m.stageStats[stageConvert] = map[string]int{"resumed": 1}
				} else if _, err := os.Stat(filepath.Join(m.workDir, "emails_raw.json")); err == nil {
					resumeStage = stageConvert
					m.stageStats[stageImport] = map[string]int{"resumed": 1}
				}
				m.currentStage = resumeStage
				return m, tea.Batch(
					m.spinner.Tick,
					runPipelineStage(m.inputFile, m.sender, m.workDir, resumeStage),
				)
			}
		case "Get Started":
			m.screen = screenFilePicker
			m.textInput.SetValue("")
			m.textInput.Placeholder = "Drag file here or type path..."
			m.textInput.Focus()
		case "Help":
			m.screen = screenHelp
		case "Uninstall":
			m.screen = screenUninstall
			m.textInput.SetValue("")
			m.textInput.Placeholder = "Type 'uninstall' here..."
			m.textInput.Focus()
			m.errMsg = ""
		case "Quit":
			return m, tea.Quit
		}

	case screenFilePicker:
		path := cleanPath(m.textInput.Value())
		if path == "" {
			m.errMsg = "Please enter a file path"
			return m, nil
		}
		if _, err := os.Stat(path); os.IsNotExist(err) {
			m.errMsg = fmt.Sprintf("File not found: %s", path)
			return m, nil
		}
		m.inputFile = path
		m.errMsg = ""
		m.screen = screenSenderFilter
		m.textInput.SetValue("")
		m.textInput.Placeholder = "Enter your email address..."
		m.statusMsg = "Detecting your email address..."
		return m, detectOwnerEmail(path)

	case screenSenderFilter:
		sender := strings.TrimSpace(m.textInput.Value())
		if sender == "" {
			m.errMsg = "Email address is required"
			return m, nil
		}
		m.sender = sender
		m.workDir, _ = os.Getwd()
		m.screen = screenProgress
		m.currentStage = stageImport
		m.errMsg = ""
		// Save job for resume
		saveJob(m.inputFile, m.workDir, "in_progress", m.sender)
		return m, tea.Batch(
			m.spinner.Tick,
			runPipelineStage(m.inputFile, m.sender, m.workDir, stageImport),
		)

	case screenResults, screenHelp:
		m.screen = screenMainMenu

	case screenUninstall:
		if strings.ToLower(strings.TrimSpace(m.textInput.Value())) == "uninstall" {
			// Do the uninstall
			cacheDir := getCacheDir()
			homeDir, _ := os.UserHomeDir()
			installDir := filepath.Join(homeDir, "voice-synth")

			os.RemoveAll(cacheDir)
			os.RemoveAll(installDir)

			fmt.Println("\n  Uninstalled successfully.")
			fmt.Println("  Run the install command again to reinstall.\n")
			return m, tea.Quit
		} else {
			m.errMsg = "Type 'uninstall' to confirm"
			return m, nil
		}
	}

	return m, nil
}

func (m model) View() string {
	switch m.screen {
	case screenSetup:
		return m.viewSetup()
	case screenMainMenu:
		return m.viewMainMenu()
	case screenFilePicker:
		return m.viewFilePicker()
	case screenSenderFilter:
		return m.viewSenderFilter()
	case screenProgress:
		return m.viewProgress()
	case screenResults:
		return m.viewResults()
	case screenHelp:
		return m.viewHelp()
	case screenUninstall:
		return m.viewUninstall()
	}
	return ""
}

func (m model) viewSetup() string {
	content := titleStyle.Render("Voice Synthesizer") + "\n"
	content += subtitleStyle.Render("Email data preparation for GPT fine-tuning") + "\n"
	content += subtitleStyle.Render("v"+version) + "\n\n"

	// Show setup steps with status
	for i, step := range m.setupSteps {
		var icon string
		var style lipgloss.Style

		if i < m.setupStep {
			// Completed
			icon = "✓"
			style = stageCompleteStyle
		} else if i == m.setupStep {
			// Current
			icon = m.spinner.View()
			style = stageRunningStyle
		} else {
			// Pending
			icon = "○"
			style = stagePendingStyle
		}

		content += fmt.Sprintf("%s %s\n", icon, style.Render(step))
	}

	if m.errMsg != "" {
		content += "\n" + errorStyle.Render(m.errMsg)
	}

	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center,
		menuStyle.Render(content))
}

func (m model) viewMainMenu() string {
	content := titleStyle.Render("Voice Synthesizer") + "\n"
	content += subtitleStyle.Render("Email data preparation for GPT fine-tuning") + "\n"
	content += subtitleStyle.Render("v"+version) + "\n\n"

	for i, item := range m.menuItems {
		cursor := "  "
		style := normalStyle
		if i == m.menuCursor {
			cursor = "▸ "
			style = selectedStyle
		}
		line := cursor + style.Render(item)
		// Show file info for resume option
		if item == "Resume previous" && m.incompleteJob != nil {
			filename := filepath.Base(m.incompleteJob.Mbox)
			line += " " + dimStyle.Render("("+filename+")")
		}
		content += line + "\n"
	}

	content += "\n" + dimStyle.Render("↑/↓ navigate • enter select • q quit")

	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center,
		menuStyle.Render(content))
}

func (m model) viewFilePicker() string {
	content := titleStyle.Render("Select Input File") + "\n"
	content += subtitleStyle.Render("Drop your Google Takeout export (.mbox, folder, or .zip)") + "\n\n"
	content += m.textInput.View() + "\n\n"
	content += dimStyle.Render("Drag from Finder into this window, then press Enter") + "\n"

	if m.errMsg != "" {
		content += "\n" + errorStyle.Render(m.errMsg)
	}

	content += "\n" + dimStyle.Render("enter continue • esc back")

	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center,
		menuStyle.Render(content))
}

func (m model) viewSenderFilter() string {
	content := titleStyle.Render("Sender Filter") + "\n"
	content += subtitleStyle.Render("Filter to emails you wrote (not received)") + "\n\n"
	content += dimStyle.Render(m.statusMsg) + "\n\n"
	content += m.textInput.View() + "\n"

	if m.errMsg != "" {
		content += "\n" + errorStyle.Render(m.errMsg)
	}

	content += "\n" + dimStyle.Render("enter continue • esc back")

	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center,
		menuStyle.Render(content))
}

func (m model) viewProgress() string {
	content := titleStyle.Render("Processing Emails") + "\n"
	content += subtitleStyle.Render("This may take a few minutes for large mailboxes") + "\n\n"

	stages := []struct {
		s    stage
		name string
	}{
		{stageImport, "Import MBOX"},
		{stageConvert, "Convert to JSONL"},
		{stageClean, "Clean & anonymize"},
		{stageCurate, "Curate shortlist"},
	}

	for _, st := range stages {
		var icon, text string
		var style lipgloss.Style

		if st.s == m.failedStage {
			// Failed
			icon = "✗"
			style = errorStyle
			text = st.name + " - failed"
		} else if stats, ok := m.stageStats[st.s]; ok {
			// Completed
			icon = "✓"
			style = stageCompleteStyle
			if count, ok := stats["kept"]; ok {
				text = fmt.Sprintf("%s (%d)", st.name, count)
			} else if count, ok := stats["imported"]; ok {
				text = fmt.Sprintf("%s (%d)", st.name, count)
			} else if count, ok := stats["shortlisted"]; ok {
				text = fmt.Sprintf("%s (%d)", st.name, count)
			} else {
				text = st.name
			}
		} else if st.s == m.currentStage && m.failedStage == -1 {
			// Running (only if no failure)
			icon = m.spinner.View()
			style = stageRunningStyle
			text = st.name + "..."
		} else {
			// Pending
			icon = "○"
			style = stagePendingStyle
			text = st.name
		}

		content += fmt.Sprintf("%s %s\n", icon, style.Render(text))
	}

	// Log box - show rolling output
	content += "\n"
	logBoxStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(dim).
		Padding(0, 1).
		Width(44).
		Height(8)

	var logContent string
	if m.errMsg != "" {
		logContent = errorStyle.Render("Error: " + m.errMsg)
	} else if len(m.logLines) > 0 {
		logContent = dimStyle.Render(strings.Join(m.logLines, "\n"))
	} else {
		logContent = dimStyle.Render("Waiting for output...")
	}
	content += logBoxStyle.Render(logContent)

	if m.errMsg != "" {
		content += "\n" + dimStyle.Render("esc to go back")
	}

	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center,
		menuStyle.Width(55).Render(content))
}

func (m model) viewResults() string {
	content := successStyle.Render("✓ Processing Complete!") + "\n\n"

	// Show output path
	home, _ := os.UserHomeDir()
	outputPath := filepath.Join(home, "Desktop", "style_shortlist.csv")
	content += "Output: " + dimStyle.Render(outputPath) + "\n\n"

	// Results table
	content += "Stage      Input    Output   Filtered\n"
	content += "─────────────────────────────────────\n"

	if stats, ok := m.results["import"]; ok {
		content += fmt.Sprintf("Import     %5d    %5d    %5d\n",
			stats["total"], stats["imported"], stats["skipped"])
	}
	if stats, ok := m.results["convert"]; ok {
		content += fmt.Sprintf("Convert    %5d    %5d    %5d\n",
			stats["total"], stats["kept"], stats["total"]-stats["kept"])
	}
	if stats, ok := m.results["clean"]; ok {
		content += fmt.Sprintf("Clean      %5d    %5d    %5d\n",
			stats["total"], stats["kept"], stats["total"]-stats["kept"])
	}
	if stats, ok := m.results["curate"]; ok {
		content += fmt.Sprintf("Curate     %5d    %5d    %5d\n",
			stats["total_input"], stats["shortlisted"], stats["total_input"]-stats["shortlisted"])
	}

	content += "\n" + dimStyle.Render("Open the CSV in a spreadsheet to review") + "\n"
	content += "\n" + dimStyle.Render("enter done • q quit")

	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center,
		menuStyle.Width(60).Render(content))
}

func (m model) viewHelp() string {
	content := titleStyle.Render("Help") + "\n\n"
	content += selectedStyle.Render("Pipeline Stages") + "\n"
	content += "0. Import   - Import MBOX, strip attachments\n"
	content += "1. Convert  - Convert to JSONL format\n"
	content += "2. Clean    - Anonymize PII with Presidio\n"
	content += "3. Curate   - Score and output CSV\n\n"

	content += selectedStyle.Render("Quick Start") + "\n"
	content += "1. Export mail from takeout.google.com\n"
	content += "2. Select your .mbox file\n"
	content += "3. Enter your email address\n"
	content += "4. Review style_shortlist.csv\n\n"

	content += selectedStyle.Render("CLI Usage") + "\n"
	content += dimStyle.Render("./voice-synth run <file> --sender <email>") + "\n"

	content += "\n" + dimStyle.Render("enter/esc back")

	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center,
		menuStyle.Width(55).Render(content))
}

func (m model) viewUninstall() string {
	content := titleStyle.Render("Uninstall") + "\n\n"
	content += "This will delete:\n"
	content += dimStyle.Render("~/.cache/voice-synth/") + "\n"
	content += dimStyle.Render("~/voice-synth/") + "\n\n"
	content += "Type " + errorStyle.Render("uninstall") + " to confirm:\n\n"
	content += m.textInput.View() + "\n"

	if m.errMsg != "" {
		content += "\n" + errorStyle.Render(m.errMsg)
	}

	content += "\n" + dimStyle.Render("enter confirm • esc cancel")

	return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center,
		menuStyle.Render(content))
}

// Job tracking for resume feature

type Job struct {
	Mbox      string `json:"mbox"`
	WorkDir   string `json:"work_dir"`
	Status    string `json:"status"`
	Sender    string `json:"sender"`
	Started   string `json:"started"`
	Updated   string `json:"updated"`
}

func getJobsFile() string {
	return filepath.Join(getCacheDir(), "jobs.json")
}

func loadJobs() []Job {
	data, err := os.ReadFile(getJobsFile())
	if err != nil {
		return []Job{}
	}
	var jobs []Job
	if err := json.Unmarshal(data, &jobs); err != nil {
		return []Job{}
	}
	return jobs
}

func saveJob(mbox, workDir, status, sender string) {
	jobs := loadJobs()
	now := time.Now().UTC().Format(time.RFC3339)

	// Update existing or add new
	found := false
	for i := range jobs {
		if jobs[i].Mbox == mbox && jobs[i].WorkDir == workDir {
			jobs[i].Status = status
			jobs[i].Updated = now
			if sender != "" {
				jobs[i].Sender = sender
			}
			found = true
			break
		}
	}

	if !found {
		jobs = append(jobs, Job{
			Mbox:    mbox,
			WorkDir: workDir,
			Status:  status,
			Sender:  sender,
			Started: now,
			Updated: now,
		})
	}

	// Keep last 10
	if len(jobs) > 10 {
		jobs = jobs[len(jobs)-10:]
	}

	data, _ := json.MarshalIndent(jobs, "", "  ")
	os.MkdirAll(getCacheDir(), 0755)
	os.WriteFile(getJobsFile(), data, 0644)
}

func getIncompleteJob() *Job {
	for _, job := range loadJobs() {
		if job.Status != "in_progress" {
			continue
		}
		// Check if work dir exists
		if _, err := os.Stat(job.WorkDir); os.IsNotExist(err) {
			continue
		}
		// Check if already completed
		if _, err := os.Stat(filepath.Join(job.WorkDir, "style_shortlist.csv")); err == nil {
			continue
		}
		// Check for intermediate files
		for _, f := range []string{"emails_raw.json", "emails.jsonl", "cleaned_emails.json"} {
			if _, err := os.Stat(filepath.Join(job.WorkDir, f)); err == nil {
				return &job
			}
		}
	}
	return nil
}

func markJobComplete(workDir string) {
	jobs := loadJobs()
	now := time.Now().UTC().Format(time.RFC3339)
	for i := range jobs {
		if jobs[i].WorkDir == workDir {
			jobs[i].Status = "completed"
			jobs[i].Updated = now
		}
	}
	data, _ := json.MarshalIndent(jobs, "", "  ")
	os.WriteFile(getJobsFile(), data, 0644)
}

// Helper functions

func cleanPath(path string) string {
	path = strings.TrimSpace(path)
	// Remove surrounding quotes
	if (strings.HasPrefix(path, "'") && strings.HasSuffix(path, "'")) ||
		(strings.HasPrefix(path, "\"") && strings.HasSuffix(path, "\"")) {
		path = path[1 : len(path)-1]
	}
	// Handle escaped spaces
	path = strings.ReplaceAll(path, "\\ ", " ")
	// Handle file:// URLs
	if strings.HasPrefix(path, "file://") {
		path = path[7:]
	}
	// Expand ~
	if strings.HasPrefix(path, "~") {
		home, _ := os.UserHomeDir()
		path = filepath.Join(home, path[1:])
	}
	return path
}

func getCacheDir() string {
	if xdg := os.Getenv("XDG_CACHE_HOME"); xdg != "" {
		return filepath.Join(xdg, "voice-synth")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".cache", "voice-synth")
}

func getVenvPython() string {
	venv := filepath.Join(getCacheDir(), "venv")
	if runtime.GOOS == "windows" {
		return filepath.Join(venv, "Scripts", "python.exe")
	}
	return filepath.Join(venv, "bin", "python3")
}

func getScriptDir() string {
	exe, _ := os.Executable()
	return filepath.Dir(exe)
}

// Commands

// Setup step constants
const (
	setupStepVenv = iota
	setupStepLightDeps
	setupStepPresidio
	setupStepSpacy
	setupStepModel
	setupStepDone
)

func runSetupStep(step int) tea.Cmd {
	return func() tea.Msg {
		cacheDir := getCacheDir()
		venvDir := filepath.Join(cacheDir, "venv")
		python := getVenvPython()

		switch step {
		case setupStepVenv:
			// Check/create venv
			if _, err := os.Stat(python); os.IsNotExist(err) {
				if err := os.MkdirAll(cacheDir, 0755); err != nil {
					return setupErrorMsg{err}
				}
				cmd := exec.Command("python3", "-m", "venv", venvDir)
				if err := cmd.Run(); err != nil {
					return setupErrorMsg{fmt.Errorf("failed to create venv: %w", err)}
				}
			}
			return setupNextMsg{setupStepLightDeps}

		case setupStepLightDeps:
			// Check if we need to install anything
			checkCmd := exec.Command(python, "-c", "import presidio_analyzer; import spacy; spacy.load('en_core_web_lg')")
			if checkCmd.Run() == nil {
				// All deps already installed
				return setupCompleteMsg{}
			}
			// Install lightweight deps
			cmd := exec.Command(python, "-m", "pip", "install", "--quiet", "ijson>=3.2.0", "datasketch>=1.6.0")
			if err := cmd.Run(); err != nil {
				return setupErrorMsg{fmt.Errorf("failed to install ijson/datasketch: %w", err)}
			}
			return setupNextMsg{setupStepPresidio}

		case setupStepPresidio:
			cmd := exec.Command(python, "-m", "pip", "install", "--quiet", "presidio-analyzer>=2.2.0", "presidio-anonymizer>=2.2.0")
			if err := cmd.Run(); err != nil {
				return setupErrorMsg{fmt.Errorf("failed to install Presidio: %w", err)}
			}
			return setupNextMsg{setupStepSpacy}

		case setupStepSpacy:
			cmd := exec.Command(python, "-m", "pip", "install", "--quiet", "spacy>=3.5.0")
			if err := cmd.Run(); err != nil {
				return setupErrorMsg{fmt.Errorf("failed to install spaCy: %w", err)}
			}
			return setupNextMsg{setupStepModel}

		case setupStepModel:
			cmd := exec.Command(python, "-m", "spacy", "download", "en_core_web_lg", "--quiet")
			if err := cmd.Run(); err != nil {
				return setupErrorMsg{fmt.Errorf("failed to download language model: %w", err)}
			}
			return setupCompleteMsg{}
		}

		return setupCompleteMsg{}
	}
}

func checkPythonSetup() tea.Msg {
	return setupNextMsg{setupStepVenv}
}

func detectOwnerEmail(inputFile string) tea.Cmd {
	return func() tea.Msg {
		python := getVenvPython()
		scriptDir := getScriptDir()
		pipelineScript := filepath.Join(scriptDir, "pipeline.py")

		cmd := exec.Command(python, pipelineScript, "detect-owner", inputFile)
		output, err := cmd.Output()
		if err != nil {
			return ownerDetectedMsg{email: ""}
		}

		email := strings.TrimSpace(string(output))
		return ownerDetectedMsg{email: email}
	}
}

func runPipelineStage(inputFile, sender, workDir string, s stage) tea.Cmd {
	return func() tea.Msg {
		python := getVenvPython()
		scriptDir := getScriptDir()
		pipelineScript := filepath.Join(scriptDir, "pipeline.py")

		var args []string
		switch s {
		case stageImport:
			args = []string{pipelineScript, "import", inputFile, "--out", "emails_raw.json", "--json-stats"}
		case stageConvert:
			// Use emails_raw.json if it exists, otherwise use inputFile
			convertInput := filepath.Join(workDir, "emails_raw.json")
			if _, err := os.Stat(convertInput); os.IsNotExist(err) {
				convertInput = inputFile
			}
			args = []string{pipelineScript, "convert", convertInput, "--out", "emails.jsonl", "--json-stats"}
		case stageClean:
			args = []string{pipelineScript, "clean", "emails.jsonl", "--out", "cleaned_emails.json", "--json-stats"}
			if sender != "" {
				args = append(args, "--sender", sender)
			}
		case stageCurate:
			args = []string{pipelineScript, "curate", "cleaned_emails.json", "--out", "style_shortlist.csv", "--json-stats"}
		}

		cmd := exec.Command(python, args...)
		cmd.Dir = workDir

		// Create pipes for stdout and stderr
		stdout, err := cmd.StdoutPipe()
		if err != nil {
			return stageErrorMsg{stage: s, err: err}
		}
		stderr, err := cmd.StderrPipe()
		if err != nil {
			return stageErrorMsg{stage: s, err: err}
		}

		// Start the command
		if err := cmd.Start(); err != nil {
			return stageErrorMsg{stage: s, err: err}
		}

		// Collect all output for parsing stats at the end
		var allOutput strings.Builder
		var lastErr string

		// Read stdout and stderr concurrently
		done := make(chan bool, 2)

		readPipe := func(pipe io.Reader, isStderr bool) {
			scanner := bufio.NewScanner(pipe)
			for scanner.Scan() {
				line := scanner.Text()
				allOutput.WriteString(line + "\n")
				if isStderr {
					lastErr = line
				}
				// Send log update to UI (truncate long lines)
				displayLine := line
				if len(displayLine) > 50 {
					displayLine = displayLine[:47] + "..."
				}
				if program != nil {
					program.Send(logUpdateMsg{line: displayLine})
				}
			}
			done <- true
		}

		go readPipe(stdout, false)
		go readPipe(stderr, true)

		// Wait for both readers
		<-done
		<-done

		// Wait for command to finish
		err = cmd.Wait()
		if err != nil {
			// Log full error details for debugging
			logFile := filepath.Join(getCacheDir(), "error.log")
			logContent := fmt.Sprintf("Stage: %d\nCommand: %s %v\nWorkDir: %s\nExit: %v\nOutput:\n%s\n",
				s, python, args, workDir, err, allOutput.String())
			os.WriteFile(logFile, []byte(logContent), 0644)

			// Try to show the most useful error info
			errMsg := lastErr
			if errMsg == "" {
				// No stderr, use last lines of stdout
				lines := strings.Split(strings.TrimSpace(allOutput.String()), "\n")
				if len(lines) > 0 {
					// Get last non-empty line
					for i := len(lines) - 1; i >= 0; i-- {
						if lines[i] != "" && !strings.HasPrefix(lines[i], "{") {
							errMsg = lines[i]
							break
						}
					}
				}
			}
			if errMsg == "" {
				errMsg = fmt.Sprintf("%v (see ~/.cache/voice-synth/error.log)", err)
			}
			return stageErrorMsg{stage: s, err: fmt.Errorf("%s", errMsg)}
		}

		// Parse JSON stats from output
		var stats map[string]int
		for _, line := range strings.Split(allOutput.String(), "\n") {
			if strings.HasPrefix(line, "{") {
				if err := json.Unmarshal([]byte(line), &stats); err == nil {
					break
				}
			}
		}

		if s == stageCurate {
			// Copy to desktop
			home, _ := os.UserHomeDir()
			desktop := filepath.Join(home, "Desktop", "style_shortlist.csv")
			src := filepath.Join(workDir, "style_shortlist.csv")
			copyFile(src, desktop)

			// Return all results
			results := make(map[string]map[string]int)
			results["curate"] = stats
			return pipelineCompleteMsg{results: results}
		}

		return stageCompleteMsg{stage: s, stats: stats}
	}
}

func copyFile(src, dst string) error {
	input, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, input, 0644)
}

func main() {
	program = tea.NewProgram(initialModel(), tea.WithAltScreen())
	if _, err := program.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
