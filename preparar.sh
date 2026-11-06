#!/usr/bin/env sh
# Prepara bria-local en Linux o macOS: baja el código si falta y crea .env con claves nuevas.
#   sh preparar.sh
set -eu
cd "$(dirname "$0")"
ORGANIZACION="${1:-bria-app}"

for repo in bria-web bria-api bria-engine; do
  if [ -d "repos/$repo" ]; then
    echo "repos/$repo ya existe"
  else
    git clone "https://github.com/$ORGANIZACION/$repo.git" "repos/$repo"
  fi
done

if [ -f .env ]; then
  echo ".env ya existe: no se cambia"
else
  clave() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; }
  contrasena() { printf 'Qa-%s-26!' "$(od -An -N5 -tx1 /dev/urandom | tr -d ' \n')"; }
  tr -d '\r' < .env.example > .env
  for nombre in POSTGRES_PASSWORD JWT_SECRET_KEY ENGINE_API_KEY; do
    sed -i.bak "s/^$nombre=\$/$nombre=$(clave)/" .env
  done
  for nombre in DEMO_OWNER_PASSWORD DEMO_SELLER_PASSWORD; do
    sed -i.bak "s/^$nombre=\$/$nombre=$(contrasena)/" .env
  done
  rm -f .env.bak
  echo ".env creado. Las contraseñas de las cuentas de prueba están en DEMO_OWNER_PASSWORD y DEMO_SELLER_PASSWORD."
fi

echo
echo "Listo. Ahora ejecuta: docker compose up --build"
echo "Y abre http://localhost:3000 cuando termine el servicio semilla."
