from flask import Flask, request, render_template, jsonify
import time

import joblib

from feature_extraction import extract_features
import ollama_client

app = Flask(__name__)
app.json.sort_keys = False  # keep feature order as the model sees it

# Load trained model
model = joblib.load("model.pkl")

# How much weight the LLM gets in the final score (0 = ML only, 1 = LLM only)
AI_WEIGHT = 0.5


def label_for(prob):
    if prob < 0.4:
        return "✅ Safe (Low Risk)"
    elif prob < 0.75:
        return "⚠️ Suspicious"
    return "❌ Phishing (High Risk)"


FEATURE_NAMES = [
    "url_length", "dot_count", "has_https", "is_ip_address", "has_at_symbol",
    "hyphen_in_domain", "subdomain_count", "http_in_domain", "path_length",
    "digit_count", "special_char_count", "suspicious_keyword", "domain_length",
    "is_url_shortener", "query_count",
]


def analyze(url, use_ai=True):
    t0 = time.time()
    features = extract_features(url)
    ml_prob = float(model.predict_proba([features])[0][1])
    t_ml = time.time()

    ai = ollama_client.analyze_url(url, ml_prob) if use_ai else None
    t_ai = time.time()

    if ai:
        final_prob = (1 - AI_WEIGHT) * ml_prob + AI_WEIGHT * (ai["risk_score"] / 100)
    else:
        final_prob = ml_prob

    return {
        "url": url,
        "result": label_for(final_prob),
        "final_score": round(final_prob * 100, 2),
        "ml_score": round(ml_prob * 100, 2),
        "ai": ai,                      # None if Ollama is off/unreachable
        "ai_model": ollama_client.OLLAMA_MODEL if ai else None,
        "features": dict(zip(FEATURE_NAMES, [int(f) for f in features])),
        "timing_ms": {
            "ml": round((t_ml - t0) * 1000, 1),
            "ai": round((t_ai - t_ml) * 1000, 1) if use_ai else 0,
        },
    }


@app.route("/")
def home():
    return render_template("index.html",
                           ai_online=ollama_client.is_available(),
                           ai_model=ollama_client.OLLAMA_MODEL)


@app.route("/predict", methods=["POST"])
def predict():
    url = request.form["url"].strip()
    use_ai = request.form.get("use_ai") == "on"
    data = analyze(url, use_ai=use_ai)
    return render_template(
        "index.html",
        url=url,
        use_ai=use_ai,
        prediction_text=data["result"],
        probability=data["final_score"],
        ml_score=data["ml_score"],
        ai=data["ai"],
        ai_model=data["ai_model"],
        ai_online=ollama_client.is_available(),
    )


@app.route("/api/predict", methods=["POST"])
def api_predict():
    """JSON API: POST {"url": "...", "use_ai": true}"""
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    return jsonify(analyze(url, use_ai=body.get("use_ai", True)))


@app.route("/api/health")
def health():
    return jsonify({
        "ml_model": "loaded",
        "ollama": ollama_client.is_available(),
        "ollama_model": ollama_client.OLLAMA_MODEL,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
