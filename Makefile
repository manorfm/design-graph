PROTO     ?= $(shell ls *.html 2>/dev/null | head -1)
DB_DIR    ?= $(shell PYTHONPATH=$(CONTEXT)/src python3 -c "from design_graph.paths import resolve_graph_dir; print(resolve_graph_dir())" 2>/dev/null || echo "$(HOME)/.local/share/design-graph")
GRAPH_DB  ?= $(DB_DIR)/$(basename $(PROTO)).db
MCP_PID   := /tmp/design-mcp.pid
MCP_LOG   := /tmp/design-mcp.log
PYTHON    := python3

# Resolve the directory where this Makefile lives (works from any cwd)
CONTEXT := $(shell dirname "$(abspath $(lastword $(MAKEFILE_LIST)))")

# Commands are provided by the package installation (pip/pipx/editable install).
DESIGN_GRAPH := design-graph
DESIGN_MCP   := design-mcp
DESIGN_QUERY := design-query

.DEFAULT_GOAL := help

# ─────────────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  design-graph"
	@echo ""
	@echo "  Graph"
	@echo "    make build   PROTO=file.html     Build / update the graph"
	@echo "    make diff    PROTO=file.html     Show what changed since last build"
	@echo "    make rebuild PROTO=file.html     Force a full rebuild"
	@echo "    make databases                   List graph databases"
	@echo "    make use-db DOC='prototype'      Select the default prototype"
	@echo "    make remove-db DOC='prototype'   Remove a graph and its state"
	@echo "    make prune-dbs                   Preview orphan cleanup"
	@echo ""
	@echo "  MCP Server"
	@echo "    make start                       Start MCP server in background"
	@echo "    make stop                        Stop MCP server"
	@echo "    make restart                     Restart MCP server"
	@echo "    make status                      Check if running"
	@echo "    make logs                        Tail server logs"
	@echo ""
	@echo "  Direct queries (no Cursor needed)"
	@echo "    make screens                     List all screens"
	@echo "    make tokens                      List color tokens"
	@echo "    make search  Q='button'          Search the graph"
	@echo "    make inspect C='SectionCard'     Component details"
	@echo "    make impact  C='SectionCard'     Impact analysis"
	@echo "    make screen  S='RestaurantsPage' Screen details"
	@echo ""
	@echo "  Developer setup"
	@echo "    make install-hooks               Install git hooks (auto-versioning)"
	@echo "    make push                        Push commits + version tags to GitHub"
	@echo "    make version                     Show current and projected next version"
	@echo ""
	@echo "  Maintenance"
	@echo "    make list-graphs                 List available graphs"
	@echo "    make clean-graph DB=~/graphs/x.db  Remove a graph"
	@echo "    make clean-all                   Remove all graphs"
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Graph
# ─────────────────────────────────────────────────────────────────────────────

build:
	@test -n "$(PROTO)"  || (echo "Error: PROTO not set. Ex: make build PROTO=file.html" && exit 1)
	@test -f "$(PROTO)"  || (echo "Error: file '$(PROTO)' not found" && exit 1)
	@mkdir -p $(DB_DIR)
	$(DESIGN_GRAPH) "$(PROTO)" --db $(GRAPH_DB)

diff:
	@test -n "$(PROTO)" || (echo "Error: PROTO not set." && exit 1)
	$(DESIGN_GRAPH) "$(PROTO)" --db $(GRAPH_DB) --diff

rebuild:
	@test -n "$(PROTO)" || (echo "Error: PROTO not set." && exit 1)
	$(DESIGN_GRAPH) "$(PROTO)" --db $(GRAPH_DB) --force

databases:
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_GRAPH) db list

use-db:
	@test -n "$(DOC)" || (echo "Usage: make use-db DOC='prototype'" && exit 1)
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_GRAPH) db use "$(DOC)"

remove-db:
	@test -n "$(DOC)" || (echo "Usage: make remove-db DOC='prototype'" && exit 1)
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_GRAPH) db remove "$(DOC)"

prune-dbs:
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_GRAPH) db prune --dry-run

# ─────────────────────────────────────────────────────────────────────────────
# MCP Server
# ─────────────────────────────────────────────────────────────────────────────

start:
	@if [ -f $(MCP_PID) ] && kill -0 $$(cat $(MCP_PID)) 2>/dev/null; then \
		echo "MCP already running (PID $$(cat $(MCP_PID)))"; \
	else \
		echo "Note: if Cursor is open with MCP active, the DB lock will prevent a second server."; \
		GRAPH_DIR=$(DB_DIR) $(DESIGN_MCP) < /dev/null >> $(MCP_LOG) 2>&1 & \
		echo $$! > $(MCP_PID); \
		sleep 2; \
		if kill -0 $$(cat $(MCP_PID)) 2>/dev/null; then \
			echo "MCP started — PID $$(cat $(MCP_PID)) | make logs"; \
		else \
			echo "MCP failed to start — Cursor may already hold the DB lock. See: make logs"; \
			rm -f $(MCP_PID); \
		fi; \
	fi

stop:
	@if [ -f $(MCP_PID) ]; then \
		PID=$$(cat $(MCP_PID)); \
		if kill -0 $$PID 2>/dev/null; then \
			kill $$PID && echo "MCP stopped (PID $$PID)."; \
		else \
			echo "PID $$PID was not running."; \
		fi; \
		rm -f $(MCP_PID); \
	else \
		STRAY=$$(pgrep -f mcp_server.py); \
		if [ -n "$$STRAY" ]; then kill $$STRAY && echo "MCP stopped (PID $$STRAY)."; \
		else echo "MCP is not running."; fi; \
	fi

restart: stop start

status:
	@if [ -f $(MCP_PID) ] && kill -0 $$(cat $(MCP_PID)) 2>/dev/null; then \
		echo "MCP running (PID $$(cat $(MCP_PID)))"; \
		ls $(DB_DIR)/*.db 2>/dev/null || echo "  (no graphs in $(DB_DIR))"; \
	else \
		echo "MCP is not running"; \
	fi

logs:
	@tail -f $(MCP_LOG)

# ─────────────────────────────────────────────────────────────────────────────
# Direct queries
# ─────────────────────────────────────────────────────────────────────────────

screens:
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_QUERY) screens

tokens:
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_QUERY) tokens color

search:
	@test -n "$(Q)" || (echo "Usage: make search Q='term'" && exit 1)
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_QUERY) search $(Q)

inspect:
	@test -n "$(C)" || (echo "Usage: make inspect C='ComponentName'" && exit 1)
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_QUERY) inspect $(C)

impact:
	@test -n "$(C)" || (echo "Usage: make impact C='ComponentName'" && exit 1)
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_QUERY) impact $(C)

screen:
	@test -n "$(S)" || (echo "Usage: make screen S='ScreenName'" && exit 1)
	@GRAPH_DIR=$(DB_DIR) $(DESIGN_QUERY) screen $(S)

# ─────────────────────────────────────────────────────────────────────────────
# Developer setup
# ─────────────────────────────────────────────────────────────────────────────

install-hooks:
	git config core.hooksPath .githooks
	git config push.followTags true
	@echo "Git hooks installed — post-commit will auto-tag versions."
	@echo "push.followTags enabled — 'git push' will now include annotated tags."
	@echo "Run 'git config --unset core.hooksPath' to remove hooks."

push:
	@echo "Pushing commits and all annotated version tags…"
	git push --follow-tags
	@echo "Done. pip install --upgrade git+<url> will now see the latest version."

version:
	@python scripts/auto_version.py --dry-run 2>/dev/null || \
	 python3 -c "import subprocess; print(subprocess.run(['git','describe','--tags','--abbrev=0'],capture_output=True,text=True).stdout.strip() or '(no tags yet)')"

# ─────────────────────────────────────────────────────────────────────────────
# Maintenance
# ─────────────────────────────────────────────────────────────────────────────

list-graphs:
	@echo "Graphs in $(DB_DIR):"
	@ls -lh $(DB_DIR)/*.db 2>/dev/null || echo "  (none)"

clean-graph:
	@test -n "$(DB)" || (echo "Usage: make clean-graph DB=~/graphs/file.db" && exit 1)
	rm -rf "$(DB)"
	@echo "Removed: $(DB)"

clean-all:
	@printf "Remove all graphs in $(DB_DIR)? [y/N] " && read c && \
	[ "$$c" = "y" ] && rm -rf $(DB_DIR)/*.db && echo "Done." || echo "Cancelled."

.PHONY: help build diff rebuild databases use-db remove-db prune-dbs start stop restart status logs \
        screens tokens search inspect impact screen \
        install-hooks push version \
        list-graphs clean-graph clean-all
