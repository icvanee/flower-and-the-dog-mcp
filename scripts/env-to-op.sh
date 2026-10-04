#!/usr/bin/env bash
# Verplaatst de secrets uit het env-bestand naar de 1Password-kluis "Mac Mini" en zet
# er op://-verwijzingen voor in de plaats. run.sh lost die op met `op run`, met het
# service-account-token uit de Keychain (mac-mini-setup: bin/op-token.sh).
#
# Draai dit zelf: het maakt items aan met je eigen 1Password-login (het service account
# kan alleen lezen). Het oude env-bestand blijft ernaast staan als env.bak (chmod 600);
# verwijder dat zodra de server op de verwijzingen draait.
#
#   scripts/env-to-op.sh [env file]
set -euo pipefail
umask 077

ENV_FILE=${1:-$HOME/.config/flower-and-the-dog-mcp/env}
VAULT="Mac Mini"
unset OP_SERVICE_ACCOUNT_TOKEN  # items schrijven met je eigen login

get() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true; }

# Maakt een item via een JSON-sjabloon in een tijdelijk bestand, zodat geen secret in `ps` verschijnt.
create_item() {
  local title=$1 category=$2 fields=$3 tmp
  if op item get "$title" --vault "$VAULT" >/dev/null 2>&1; then
    echo "  $title: bestaat al, niet aangeraakt"; return
  fi
  tmp=$(mktemp)
  printf '{"title": %s, "category": "%s", "fields": %s}' "$(jq -Rn --arg t "$title" '$t')" "$category" "$fields" > "$tmp"
  op item create --vault "$VAULT" --template "$tmp" >/dev/null
  rm -f "$tmp"
  echo "  $title: aangemaakt"
}

field() {  # id label type value
  jq -n --arg id "$1" --arg label "$2" --arg type "$3" --arg value "$4" \
    '{id: $id, label: $label, type: $type, value: $value}
     + (if $id == "username" then {purpose: "USERNAME"} elif $id == "password" then {purpose: "PASSWORD"} else {} end)'
}

replace() {  # VAR reference
  sed -i '' "s#^$1=.*#$1=$2#" "$ENV_FILE"
}

[ -f "$ENV_FILE" ] || { echo "geen env-bestand op $ENV_FILE"; exit 1; }
cp "$ENV_FILE" "$ENV_FILE.bak"
echo "1Password-kluis: $VAULT"

v=$(get MCP_LOGIN_PASSWORD)
if [ -n "$v" ] && [[ $v != op://* ]]; then
  create_item "MCP login" PASSWORD "[$(field password password CONCEALED "$v")]"
  replace MCP_LOGIN_PASSWORD "op://$VAULT/MCP login/password"
fi

v=$(get HEALTH_DATABASE_URL)
if [ -n "$v" ] && [[ $v != op://* ]]; then
  create_item "Health DB mcp" PASSWORD "[$(field password password CONCEALED "$v")]"
  replace HEALTH_DATABASE_URL "op://$VAULT/Health DB mcp/password"
fi

u=$(get CARWASH_USERNAME); p=$(get CARWASH_PASSWORD)
if [ -n "$p" ] && [[ $p != op://* ]]; then
  create_item "Carwash Kleiboer" LOGIN \
    "[$(field username username STRING "$u"), $(field password password CONCEALED "$p")]"
  replace CARWASH_USERNAME "op://$VAULT/Carwash Kleiboer/username"
  replace CARWASH_PASSWORD "op://$VAULT/Carwash Kleiboer/password"
fi

echo "het env-bestand bevat nu:"
grep -E '^[A-Z_]+=' "$ENV_FILE" | sed -E 's/=(op:\/\/.*)$/=\1/; s/=([^o].*|o[^p].*)$/=<plain>/' | sed 's/^/  /'
echo "herstart de server: cd ~/Source/mac-mini-setup && ./install-agents.sh mcp"
