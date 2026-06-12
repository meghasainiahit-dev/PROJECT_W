# StockOS Mobile WebView App

This Flutter app opens the StockOS Django web app inside a native mobile WebView.

## Run Django

From the project root:

```bash
source /Users/ankitsamant/PROJECT_W/env/bin/activate
python manage.py runserver 0.0.0.0:8000
```

## Run Flutter

From `stockos_mobile`:

```bash
flutter run
```

Default URL:

```text
http://10.0.2.2:8000/dashboard/
```

That default works for the Android emulator. For iOS simulator or a real device, pass your own URL:

```bash
flutter run --dart-define=STOCKOS_URL=http://127.0.0.1:8000/dashboard/
```

For a physical phone, use your Mac's LAN IP:

```bash
flutter run --dart-define=STOCKOS_URL=http://YOUR_MAC_IP:8000/dashboard/
```

Make sure the phone and Mac are on the same Wi-Fi, and Django is running with `0.0.0.0:8000`.
