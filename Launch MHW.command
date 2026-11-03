#!/bin/bash
# Open the application from Finder, using this project's interpreter.
cd -- "$(dirname -- "$0")" || exit 1
if [ -x .venv-modern/bin/python ]; then
    .venv-modern/bin/python main.py
elif [ -x .venv/bin/python ]; then
    .venv/bin/python main.py
else
    python3 main.py
fi
result=$?
if [ "$result" -ne 0 ]; then
    echo "The app could not start. See the error above."
    read -r -p "Press Enter to close this window."
fi
exit "$result"
