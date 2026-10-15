#!/usr/bin/env bash
# Create .env from .env.example by asking for each setting. Passwords are generated; keys can be left empty
# (press Enter) and filled in later with a text editor. Never commit .env.
#   bash scripts/make-env.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  read -r -p ".env bestaat al. Overschrijven? (j/N) " answer
  [ "$answer" = "j" ] || { echo "Niets veranderd."; exit 0; }
  cp .env ".env.backup-$(date +%Y%m%d%H%M%S)"
fi

command -v openssl >/dev/null || { echo "openssl ontbreekt"; exit 1; }
random() { openssl rand -hex 24; }
# macOS has bash 3.2: no associative arrays, so one variable per key (v_<KEY>).
set_value() { printf -v "v_$1" '%s' "$2"; }

ask() {  # ask KEY "question" [secret]
  local key=$1 question=$2 secret=${3:-} input
  if [ -n "$secret" ]; then read -r -s -p "$question: " input; echo; else read -r -p "$question: " input; fi
  case "$input" in
    *'"'*|*'$'*|*'`'*|*'\'*) echo "  Tekens \" \$ \` en \\ zijn niet toegestaan; laat leeg en vul later in."; input="";;
  esac
  set_value "$key" "$input"
}

echo "Graadmeter: instellingen. Druk op Enter om iets over te slaan."
echo
set_value POSTGRES_PASSWORD "$(random)"
echo "Databasewachtwoord: automatisch gemaakt (hoef je nergens in te typen)."
read -r -p "Inlogwachtwoord voor de app (Enter = maak er een voor me): " -s app; echo
if [ -z "$app" ]; then app=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20); echo "  Gemaakt: $app  <- bewaar dit in je wachtwoordbeheerder"; fi
set_value APP_PASSWORD "$app"
set_value SESSION_SECRET "$(random)"
ask COINGECKO_API_KEY "CoinGecko Demo-sleutel (begint met CG-)"
ask FRED_API_KEY "FRED-sleutel (32 tekens)"
ask TIINGO_API_KEY "Tiingo-sleutel (optioneel)"
ask EIA_API_KEY "EIA-sleutel (optioneel)"
read -r -p "Je naam en e-mailadres voor de SEC, bijv. 'Jan Jansen jan@voorbeeld.nl': " sec
if [ -n "$sec" ]; then set_value SEC_USER_AGENT "Graadmeter prive $sec"; fi
ask ANTHROPIC_API_KEY "Anthropic-sleutel voor toelichtingen (optioneel, begint met sk-ant-)" secret
ask NOTIFY_WEBHOOK_URL "Webhook voor meldingen, bijv. https://ntfy.sh/<geheime-naam> (optioneel)"

tmp=$(mktemp)
while IFS= read -r line || [ -n "$line" ]; do
  key=${line%%=*}
  name="v_$key"
  if [[ "$line" =~ ^[A-Z_]+= ]] && [ -n "${!name:-}" ]; then
    printf '%s="%s"\n' "$key" "${!name}" >> "$tmp"
  else
    printf '%s\n' "$line" >> "$tmp"
  fi
done < .env.example
mv "$tmp" .env
chmod 600 .env
echo
echo "Klaar: .env gemaakt (alleen leesbaar voor jou). Controleer of bekijk hem met: open -e .env"
