<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover" />
  <meta name="theme-color" content="#0b1220" />

  <!-- iOS PWA -->
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="SafeLine">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">

  <!-- Manifest & icons -->
  <link rel="manifest" href="/manifest.webmanifest" />
  <link rel="icon" href="/icons/icon-192.png" />
  <link rel="apple-touch-icon" href="/icons/icon-192.png" />

  <title>SafeLine</title>

  <style>
    html, body {
      height: 100%;
      margin: 0;
      background: #0b1220;
      font-family: system-ui, -apple-system, BlinkMacSystemFont,
                   "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* Topbar */
    .topbar {
      height: 56px;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 12px;
      color: #ffffff;
      font-weight: 800;
      font-size: 16px;
      position: sticky;
      top: 0;
      z-index: 100;
      backdrop-filter: blur(12px);
      background: rgba(11,18,32,0.85);
      border-bottom: 1px solid rgba(255,255,255,0.08);
    }

    .actions { margin-left:auto; display:flex; gap:8px; }

    .iconbtn {
      width: 40px;
      height: 40px;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(255,255,255,0.06);
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }

    .wrap { height: calc(100% - 56px); position: relative; }
    iframe { width:100%; height:100%; border:0; background:#fff; }

    /* FaceID modal */
    .faceid {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.55);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 999;
    }

    .faceid-card {
      width: 280px;
      background: #111827;
      border-radius: 24px;
      padding: 22px 18px;
      color: #fff;
      text-align: center;
      box-shadow: 0 30px 80px rgba(0,0,0,0.5);
    }

    .faceid-icon {
      font-size: 42px;
      margin-bottom: 10px;
    }

    .faceid-title {
      font-weight: 900;
      margin-bottom: 6px;
    }

    .faceid-text {
      opacity: 0.85;
      font-size: 14px;
      margin-bottom: 16px;
    }

    .faceid-actions {
      display: flex;
      gap: 10px;
    }

    .faceid-btn {
      flex: 1;
      border: 0;
      border-radius: 14px;
      padding: 10px;
      font-weight: 800;
      cursor: pointer;
    }

    .allow { background:#22c55e; color:#062e12; }
    .deny { background:#ef4444; color:#2b0606; }

    .hidden { display:none; }
  </style>
</head>

<body>
  <div class="topbar">
    🛡️ SafeLine
    <div class="actions">
      <button class="iconbtn" id="adminBtn" title="Admin">⚙️</button>
    </div>
  </div>

  <div class="wrap">
    <iframe
      id="appFrame"
      src="https://safeline-mvp-idev9dt6u55ne4hfzejhxu.streamlit.app/?embed=true&toolbar=false"
      referrerpolicy="no-referrer"
    ></iframe>
  </div>

  <!-- FaceID Modal -->
  <div id="faceIdModal" class="faceid hidden">
    <div class="faceid-card">
      <div class="faceid-icon">🙂</div>
      <div class="faceid-title">Face ID</div>
      <div class="faceid-text">Admin paneline erişmek için doğrula</div>
      <div class="faceid-actions">
        <button class="faceid-btn deny" id="faceCancel">İptal</button>
        <button class="faceid-btn allow" id="faceOk">Devam</button>
      </div>
    </div>
  </div>

  <script>
    const ADMIN_KEY = "safeline_admin_verified";
    const frame = document.getElementById("appFrame");
    const modal = document.getElementById("faceIdModal");

    // Admin butonu
    document.getElementById("adminBtn").addEventListener("click", () => {
      if (localStorage.getItem(ADMIN_KEY) === "true") {
        showFaceId();
      } else {
        // İlk giriş: direkt Streamlit admin sekmesi
        frame.src = frame.src.split("?")[0] + "?embed=true&toolbar=false&tab=admin";
      }
    });

    function showFaceId() {
      modal.classList.remove("hidden");
    }

    document.getElementById("faceOk").addEventListener("click", () => {
      modal.classList.add("hidden");
      frame.src = frame.src.split("?")[0] + "?embed=true&toolbar=false&tab=admin";
    });

    document.getElementById("faceCancel").addEventListener("click", () => {
      modal.classList.add("hidden");
    });

    // Streamlit tarafı ilk admin PIN’den sonra bunu set edebilir
    // Şimdilik manuel olarak set ediyoruz:
    window.addEventListener("message", (e) => {
      if (e.data === "ADMIN_VERIFIED") {
        localStorage.setItem(ADMIN_KEY, "true");
      }
    });
  </script>
</body>
</html>
