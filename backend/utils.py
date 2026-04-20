import os
import re
import sys
import math
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter
from typing import Dict, List, Tuple, Any, Optional

import joblib
# Heavy imports moved to lazy loaders below

warnings.filterwarnings("ignore")

# ── Global reproducibility ───────────────────────────────────────────────────
RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)

# Global instances (lazy-loaded)
_nlp = None
_embedder = None

def get_nlp():
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except (OSError, ImportError):
            _nlp = None
    return _nlp

def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedder

# ── Feature helps & constants ───────────────────────────────────────────────

DISFLUENCY_TOKENS = {
    "um", "uh", "er", "ah", "hmm", "hm", "erm", "uhh", "umm",
    "like", "you know", "i mean", "well", "so", "basically",
    "actually", "literally", "right", "okay", "ok"
}
NEGATIVE_WORDS = {
    "no", "not", "never", "nothing", "nobody", "nowhere", "neither",
    "nor", "without", "cant", "cannot", "wont", "dont", "doesnt",
    "didnt", "wasnt", "arent", "isnt", "hadnt", "hasnt", "havent",
    "bad", "terrible", "horrible", "awful", "wrong", "fail", "failed",
    "sad", "unhappy", "depressed", "fear", "scared", "worried", "hate",
    "worst", "useless", "stupid", "dead", "die", "hurt", "pain", "sick",
    "lonely", "alone", "hopeless", "helpless", "worthless", "empty"
}

LING_FEATURES = {
    "type_token_ratio", "repetition_rate", "disfluency_ratio",
    "negative_word_ratio", "word_entropy", "bigram_diversity",
    "coherence_len_drift", "coherence_len_std", "semantic_coherence",
    "first_person_ratio", "sentence_fragmentation"
}

CLINICAL_RULES = [
    ("type_token_ratio",    "low",  0.40, 3,
     "Reduced lexical diversity (TTR = {val:.3f})",
     "Poverty of speech (alogia): limited vocabulary range may reflect restricted language production associated with negative symptoms."),
    ("repetition_rate",     "high", 0.35, 3,
     "Elevated word repetition rate ({val:.3f})",
     "Perseverative or repetitive speech may indicate thought perseveration or reduced cognitive flexibility."),
    ("disfluency_ratio",    "high", 0.10, 2,
     "High disfluency filler rate ({val:.3f})",
     "Frequent fillers (um, uh, like) may signal word-finding difficulties or disorganised thought-to-speech conversion."),
    ("negative_word_ratio", "high", 0.06, 2,
     "Elevated negative affect language ({val:.3f})",
     "Above-average negation and negative-affect words may reflect dysphoric mood, hopelessness, or avoidant ideation."),
    ("word_entropy",        "low",  3.00, 2,
     "Low word-distribution entropy ({val:.3f} bits)",
     "Reduced entropy indicates a narrow, predictable vocabulary consistent with alogia or impoverished thought content."),
    ("bigram_diversity",    "low",  0.50, 1,
     "Low bigram phrase diversity ({val:.3f})",
     "Limited bigram variety suggests formulaic or stereotyped speech patterns."),
    ("semantic_coherence",  "low",  0.60, 3,
     "Low semantic coherence ({val:.2f})",
     "Low average cosine similarity between consecutive sentences may indicate loose associations, tangentiality, or thought disorganization."),
    ("coherence_len_drift", "high", 8.00, 2,
     "High inter-sentence length drift ({val:.2f} words/transition)",
     "Abrupt sentence length changes between consecutive utterances may reflect derailed or tangential thought flow (loose associations)."),
    ("coherence_len_std",   "high", 10.0, 1,
     "High sentence-length variability (σ = {val:.2f})",
     "Elevated variance in sentence length suggests inconsistent utterance structure, possibly reflecting disorganised speech planning."),
    ("first_person_ratio",  "high", 0.07, 2,
     "Elevated first-person pronoun ratio ({val:.3f})",
     "High usage of first-person pronouns may indicate self-referential speech or preoccupation with personal experiences, potentially seen in some thought disorders."),
    ("sentence_fragmentation", "high", 0.20, 2,
     "High sentence fragmentation ({val:.3f})",
     "Frequent short, incomplete sentences may indicate impoverished syntax, thought blocking, or difficulty maintaining coherent sentence structure."),
    ("sent_len_mean",       "low",  6.00, 2,
     "Short average sentence length ({val:.1f} words/sentence)",
     "Markedly abbreviated sentences may reflect impoverished syntax or cognitive slowing (bradyphrenia)."),
    ("dep_depth_mean",      "low",  3.00, 2,
     "Shallow syntactic dependency trees (depth = {val:.2f})",
     "Low parse-tree depth indicates syntactically simple structures, consistent with reduced clause embedding and less complex propositional content."),
    ("clause_count_ratio",  "low",  0.04, 1,
     "Sparse subordinate clause usage ({val:.4f})",
     "Infrequent embedded clauses (relative, complement, adverbial) reflect reduced syntactic complexity and elaboration."),
    ("pronoun_ratio",       "high", 0.20, 2,
     "Elevated pronoun-to-noun ratio ({val:.3f})",
     "Overuse of pronouns may produce ambiguous reference chains — a marker of loose associations or referential confusion."),
    ("verb_ratio",          "low",  0.12, 1,
     "Reduced verb density ({val:.3f})",
     "Low verb proportion may indicate sparse predication and impoverished propositional structure."),
]

# ── Cleaning & Extraction Logic ──────────────────────────────────────────────

def clean_text(raw: str) -> str:
    t = re.sub(r"\[.*?\]", " ", raw)
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"^[A-Z][a-z]*\s*:", " ", t, flags=re.MULTILINE)
    t = re.sub(r"[^a-zA-Z0-9\s'.,!?-]", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()

def _ttr(tok):
    return len(set(tok)) / len(tok) if tok else 0.0

def _rep(tok):
    if not tok: return 0.0
    return sum(c for c in Counter(tok).values() if c > 1) / len(tok)

def _disf(tok):
    return sum(1 for t in tok if t in DISFLUENCY_TOKENS) / len(tok) if tok else 0.0

def _neg(tok):
    return sum(1 for t in tok if t in NEGATIVE_WORDS) / len(tok) if tok else 0.0

def _entropy(tok):
    if not tok: return 0.0
    freq = Counter(tok); n = len(tok)
    return -sum((c/n) * math.log2(c/n) for c in freq.values())

def _bigram_div(tok):
    if len(tok) < 2: return 0.0
    bg = list(zip(tok[:-1], tok[1:]))
    return len(set(bg)) / len(bg)

def _coherence(clean: str) -> Dict[str, float]:
    sents = [s.strip() for s in re.split(r'[.!?]+', clean) if s.strip()]
    lens  = [len(s.split()) for s in sents if s.split()]
    if len(lens) < 2:
        return {"coherence_len_std": 0.0, "coherence_len_drift": 0.0}
    drift = float(np.mean([abs(lens[i] - lens[i-1]) for i in range(1, len(lens))]))
    return {"coherence_len_std": float(np.std(lens)), "coherence_len_drift": drift}

def semantic_coherence(text):
    sentences = [s.strip() for s in text.split('.') if s.strip()]
    if len(sentences) < 2: return 1.0
    from sklearn.metrics.pairwise import cosine_similarity
    embedder = get_embedder()
    embeddings = embedder.encode(sentences)
    sims = []
    for i in range(1, len(embeddings)):
        sim = cosine_similarity([embeddings[i-1]], [embeddings[i]])[0][0]
        sims.append(sim)
    return float(np.mean(sims))

def first_person_ratio(tokens):
    first_person = {"i", "me", "my", "mine", "myself"}
    return sum(1 for t in tokens if t in first_person) / len(tokens) if tokens else 0.0

def sentence_fragmentation(text):
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    if not sentences: return 0.0
    short_sentences = sum(1 for s in sentences if len(s.split()) < 5)
    return short_sentences / len(sentences)

def _dep_depth(sent) -> int:
    memo = {}
    def d(t):
        if t in memo: return memo[t]
        memo[t] = 0 if t.head == t else 1 + d(t.head)
        return memo[t]
    return max((d(tok) for tok in sent), default=0)

def _syntactic(doc) -> Dict[str, float]:
    if doc is None: 
        return {k: 0.0 for k in ["noun_ratio", "verb_ratio", "pronoun_ratio", "adj_ratio", "adv_ratio", "sent_len_mean", "sent_len_var", "dep_depth_mean", "clause_count_ratio"]}
    sents = list(doc.sents)
    if not sents:
        return {k: 0.0 for k in ["noun_ratio", "verb_ratio", "pronoun_ratio", "adj_ratio", "adv_ratio", "sent_len_mean", "sent_len_var", "dep_depth_mean", "clause_count_ratio"]}
    toks  = [t for t in doc if not t.is_space]
    n     = max(len(toks), 1)
    pos   = Counter(t.pos_ for t in toks)
    slens = [len([t for t in s if not t.is_space]) for s in sents]
    cdeps = {"ccomp", "advcl", "relcl", "acl", "xcomp"}
    return {
        "noun_ratio"         : (pos.get("NOUN", 0) + pos.get("PROPN", 0)) / n,
        "verb_ratio"         : pos.get("VERB", 0) / n,
        "pronoun_ratio"      : pos.get("PRON", 0) / n,
        "adj_ratio"          : pos.get("ADJ",  0) / n,
        "adv_ratio"          : pos.get("ADV",  0) / n,
        "sent_len_mean"      : float(np.mean(slens)),
        "sent_len_var"       : float(np.var(slens)),
        "dep_depth_mean"     : float(np.mean([_dep_depth(s) for s in sents])),
        "clause_count_ratio" : sum(1 for t in toks if t.dep_ in cdeps) / n,
    }

def extract_features(raw_text: str) -> Dict[str, float]:
    clean  = clean_text(raw_text)
    tokens = clean.split()
    nlp = get_nlp()
    doc    = nlp(clean[:50_000]) if nlp else None
    return {
        "type_token_ratio"    : _ttr(tokens),
        "repetition_rate"     : _rep(tokens),
        "disfluency_ratio"    : _disf(tokens),
        "negative_word_ratio" : _neg(tokens),
        "word_entropy"        : _entropy(tokens),
        "bigram_diversity"    : _bigram_div(tokens),
        "total_word_count"    : float(len(tokens)),
        **_coherence(clean),
        "semantic_coherence": semantic_coherence(raw_text),
        "first_person_ratio": first_person_ratio(tokens),
        "sentence_fragmentation": sentence_fragmentation(raw_text),
        **_syntactic(doc),
    }

# ── Report Generation Logic ──────────────────────────────────────────────────

def _interpret(bm: Dict) -> List[Dict]:
    out = []
    for feat, direction, thr, weight, tmpl, note in CLINICAL_RULES:
        val = bm.get(feat, 0.0)
        if (direction == "high" and val > thr) or (direction == "low" and val < thr):
            out.append({"feature": feat, "value": val, "direction": direction,
                        "threshold": thr, "weight": weight,
                        "finding": tmpl.format(val=val), "clinical": note})
    return sorted(out, key=lambda x: x["weight"], reverse=True)

def _wrap(text: str, width: int = 66, indent: str = "    ") -> str:
    words, buf, lines = text.split(), "", []
    for w in words:
        if len(buf) + len(w) + 1 > width:
            lines.append(f"{indent}{buf.rstrip()} Alvarado "); buf = w + " " # Fixed from user's manual wrap
        else:
            buf += w + " "
    if buf.strip(): lines.append(f"{indent}{buf.rstrip()}")
    return "\n".join(lines).replace(" Alvarado ", "\n" + indent) # Small fix to wrap logic

def generate_report(
    filename: str,
    label_str: str,
    prob_schiz: float,
    threshold: float,
    margin: float,
    biomarkers: Dict,
    triggered: List[Dict]
) -> str:
    ling_trig = [t for t in triggered if t["feature"] in LING_FEATURES]
    synt_trig = [t for t in triggered if t["feature"] not in LING_FEATURES]
    n_strong  = sum(1 for t in triggered if t["weight"] >= 2)
    n_total   = len(triggered)

    L = [
        "="*72,
        "         PATIENT SPEECH ANALYSIS REPORT",
        "         (Research Prototype — NOT for Clinical Use)",
        "="*72,
        f"  File              : {filename}",
        f"  Classification    : {label_str}",
        f"  P(Schizophrenia)  : {prob_schiz:.4f}",
        f"  Decision threshold: {threshold:.4f}  "
        f"(uncertain if |P - t| < {margin:.4f})",
        "-"*72, ""
    ]

    L += ["  BIOMARKER SUMMARY",
          "  " + "-"*68,
          f"  {'Feature':<28}{'Value':>9}  {'Ref':>10}  {'Flag':>7}",
          "  " + "-"*68]
    for feat, direction, thr, _, _, _ in CLINICAL_RULES:
        val  = biomarkers.get(feat, 0.0)
        flag = ("↑ HIGH" if direction == "high" and val > thr else
                "↓ LOW"  if direction == "low"  and val < thr  else "")
        ref  = f"{'>' if direction=='low' else '<'}{thr}"
        L.append(f"  {feat:<28}{val:>9.4f}  {ref:>10}  {flag:>7}")
    L += ["  " + "-"*68, ""]

    L += ["  1. LINGUISTIC FINDINGS", "  " + "─"*42]
    L += ([f"  • {t['finding']}" for t in ling_trig]
          if ling_trig else ["  • No notable linguistic deviations detected."])
    L.append("")

    L += ["  2. SYNTACTIC FINDINGS", "  " + "─"*42]
    L += ([f"  • {t['finding']}" for t in synt_trig]
          if synt_trig else ["  • No notable syntactic deviations detected."])
    L.append("")

    L += ["  3. CLINICAL INTERPRETATION", "  " + "─"*42]
    if triggered:
        for t in triggered:
            sym = "⚠ " if t["weight"] >= 2 else "◦ "
            L.append(f"  {sym}[{t['feature']}]")
            L.append(_wrap(t["clinical"]))
            L.append("")
    else:
        L += ["  No clinically significant speech deviations flagged.", ""]

    if label_str == "SCHIZOPHRENIA":
        imp = ("Multiple high-weight biomarkers converge on a pattern consistent with schizophrenia-spectrum speech: reduced lexical diversity, syntactic simplification, and markers of thought disorganisation are jointly present." if n_strong >= 4 else "Moderate biomarker evidence for atypical speech. Several language indices deviate from control norms in schizophrenia-consistent directions." if n_strong >= 2 else "Classifier probability exceeds the calibrated threshold. Individual feature signals are mild; clinical interpretation should be cautious.")
    elif label_str == "UNCERTAIN":
        imp = (f"Borderline probability (P = {prob_schiz:.3f}) falls within the uncertainty zone [{threshold-margin:.3f}, {threshold+margin:.3f}]. The model cannot confidently assign either label. This may reflect genuinely ambiguous speech patterns or a profile not well represented in the training data. Additional clinical assessment is recommended.")
    else:  # CONTROL
        imp = ("Speech indices are broadly within typical control ranges. No convergent markers of schizophrenia-spectrum language pathology detected." if n_total == 0 else f"Speech classified as control-typical despite {n_total} flagged biomarker(s). Isolated deviations do not necessarily indicate pathology; P(schizophrenia) = {prob_schiz:.3f} falls below the calibrated threshold.")

    L += ["  4. OVERALL IMPRESSION", "  " + "─"*42,
          _wrap(imp, indent="  "), ""]
    L += ["─"*72,
          "  ⚠  DISCLAIMER: Research prototype only. Not validated for clinical use.",
          "     Must NOT be used for diagnosis, treatment, or clinical decisions.",
          "="*72]
    return "\n".join(L)

# ── Inference Engine ─────────────────────────────────────────────────────────

def predict_text(
    text: str,
    model: Any,
    feature_names: List[str],
    threshold: float,
    margin: float,
    scaler: Any,
    filename: str = "input.txt",
) -> Dict:
    bm  = extract_features(text)
    x   = np.nan_to_num(
        np.array([[bm.get(f, 0.0) for f in feature_names]], dtype=np.float32),
        nan=0.0
    )
    x   = scaler.transform(x)
    prob = float(model.predict_proba(x)[0, 1])

    if prob >= threshold + margin:
        label_str   = "SCHIZOPHRENIA"
        pred_binary = 1
    elif prob <= threshold - margin:
        label_str   = "CONTROL"
        pred_binary = 0
    else:
        label_str   = "UNCERTAIN"
        pred_binary = -1

    triggered = _interpret(bm)
    report    = generate_report(filename, label_str, prob, threshold, margin, bm, triggered)
    
    return {
        "prediction" : pred_binary,
        "label_str"  : label_str,
        "prob_schiz" : round(prob, 4),
        "threshold"  : round(threshold, 4),
        "margin"     : round(margin, 4),
        "biomarkers" : {k: round(v, 5) for k, v in bm.items()},
        "triggered"  : triggered,
        "report"     : report,
    }

# Whisper logic
_stt_model = None

def get_stt_model():
    global _stt_model
    if _stt_model is None:
        import whisper
        _stt_model = whisper.load_model("base")
    return _stt_model

def audio_to_text(audio_path):
    model = get_stt_model()
    result = model.transcribe(audio_path)
    return result["text"]
