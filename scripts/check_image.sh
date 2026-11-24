#!/bin/sh
# check_image.sh IMAGE [SUMMARY.md] — проверки образа (ТЗ 1.5.4):
#   нет /app/.env и *.sqlite; процесс не root; в docker history нет TINVEST_TOKEN=<значение>;
#   `fm mcp check` без токена — понятная ошибка конфигурации (код 2), без трейсбека.
set -eu
image=$1
summary=${2:-}
fail=0
report=""

ok() { report="$report
- ✅ $1"; echo "ok: $1"; }
bad() { report="$report
- ❌ $1"; echo "FAIL: $1" >&2; fail=1; }

# 1. Нет .env и баз данных
found=$(docker run --rm --network none --entrypoint /bin/sh "$image" -c \
  'ls -a /app/.env 2>/dev/null; find / -xdev \( -name "*.sqlite" -o -name "*.sqlite-*" -o -name ".env" \) -not -path "/proc/*" 2>/dev/null' || true)
if [ -z "$found" ]; then ok "нет .env и *.sqlite"; else bad "в образе есть: $found"; fi

# 2. Не root: и в конфигурации образа, и у реального процесса
cfg_user=$(docker image inspect -f '{{.Config.User}}' "$image")
uid=$(docker run --rm --network none --entrypoint id "$image" -u)
if [ "$uid" != "0" ] && [ -n "$cfg_user" ] && [ "${cfg_user%%:*}" != "0" ] && [ "${cfg_user%%:*}" != "root" ]; then
  ok "процесс не root (uid $uid, USER $cfg_user)"
else
  bad "процесс root (uid $uid, USER '$cfg_user')"
fi

# 3. Токена нет в истории слоёв и в ENV образа
if docker history --no-trunc --format '{{.CreatedBy}}' "$image" | grep -Eq 'TINVEST_TOKEN=[^[:space:]"]'; then
  bad "docker history содержит TINVEST_TOKEN=<значение>"
elif docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$image" | grep -q '^TINVEST_TOKEN='; then
  bad "ENV образа содержит TINVEST_TOKEN"
else
  ok "TINVEST_TOKEN нет в docker history и ENV"
fi

# 4. Без токена — понятная ошибка конфигурации
set +e
out=$(docker run --rm --network none "$image" mcp check 2>&1)
code=$?
set -e
if [ "$code" -eq 2 ] && echo "$out" | grep -q "TINVEST_TOKEN" && ! echo "$out" | grep -q "Traceback"; then
  ok "fm mcp check без токена: код 2, сообщение о TINVEST_TOKEN, без трейсбека"
else
  bad "fm mcp check без токена: код $code, вывод: $out"
fi

size=$(docker image inspect -f '{{.Size}}' "$image")
size_mb=$((size / 1024 / 1024))
echo "размер образа: ${size_mb} МБ"

if [ -n "$summary" ]; then
  mkdir -p "$(dirname "$summary")"
  {
    echo "### Образ \`$image\`"
    echo
    echo "Размер: ${size_mb} МБ"
    echo "$report"
  } > "$summary"
fi
exit $fail
