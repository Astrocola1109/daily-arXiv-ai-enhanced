#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
.venv/bin/python -m digest setup-mail
printf '\n按回车关闭此设置窗口。'
read -r _digest_done
