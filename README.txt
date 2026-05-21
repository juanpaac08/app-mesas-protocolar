# App Mesas Protocolar v4 - Google Sheets

Esta versión usa Google Sheets como base de datos.

Archivos incluidos:
- app.py
- Layout_Almuerzo_v1.jpg
- Posiciones_Mesas.csv
- requirements.txt
- .streamlit/secrets.toml.example

## Google Sheet conectado

Spreadsheet ID:
1-__QYpgasM2bHjK0amIgZIrDXlLLOGSf40yLUky3DUU

## Hojas requeridas

El Google Sheet debe tener estas hojas:
- Asistentes
- Mesas

## Ejecutar local

1. Crea una carpeta .streamlit
2. Copia secrets.toml.example como secrets.toml
3. Rellena tus credenciales reales de Google Cloud Service Account
4. Comparte el Google Sheet con el correo client_email de la service account como Editor
5. Ejecuta:

pip install -r requirements.txt
streamlit run app.py

## Streamlit Cloud

En Settings → Secrets pega el contenido real del secrets.toml.
