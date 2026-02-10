MK_FILES := $(sort $(wildcard make/*.mk))
-include $(MK_FILES)

.DEFAULT_GOAL := help
.PHONY: $(shell awk -F: '/^[a-zA-Z0-9_-]+:([^=]|$$)/ {print $$1}' $(MAKEFILE_LIST))

require = $(if $(value $(1)),,$(error Missing required variable: $(1). Example: make $(MAKECMDGOALS) $(1)=<value>))

help:  ## Show available commands
	@echo "Available commands:"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  make %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
