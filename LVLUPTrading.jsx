import { useState, useEffect, useRef } from "react";

// ── HOOK: scroll-triggered visibility ──────────────────────────────────────
function useInView(threshold = 0.15) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) setVisible(true); },
      { threshold }
    );
    if (ref.current) obs.observe(ref.current);
    return () => obs.disconnect();
  }, []);
  return [ref, visible];
}

// ── ANIMATED COUNTER ───────────────────────────────────────────────────────
function Counter({ end, suffix = "", prefix = "", duration = 2000 }) {
  const [count, setCount] = useState(0);
  const [ref, visible] = useInView(0.3);
  useEffect(() => {
    if (!visible) return;
    let start = 0;
    const step = end / (duration / 16);
    const timer = setInterval(() => {
      start += step;
      if (start >= end) { setCount(end); clearInterval(timer); }
      else setCount(Math.floor(start));
    }, 16);
    return () => clearInterval(timer);
  }, [visible, end, duration]);
  return <span ref={ref}>{prefix}{count.toLocaleString()}{suffix}</span>;
}

// ── PARTICLE BACKGROUND ────────────────────────────────────────────────────
function ParticleCanvas() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    let w = canvas.width = window.innerWidth;
    let h = canvas.height = window.innerHeight;
    const particles = Array.from({ length: 60 }, () => ({
      x: Math.random() * w, y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
      r: Math.random() * 1.5 + 0.5,
      alpha: Math.random() * 0.4 + 0.1,
    }));
    let raf;
    function draw() {
      ctx.clearRect(0, 0, w, h);
      particles.forEach(p => {
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0) p.x = w; if (p.x > w) p.x = 0;
        if (p.y < 0) p.y = h; if (p.y > h) p.y = 0;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(56,182,255,${p.alpha})`;
        ctx.fill();
      });
      // Draw connections
      particles.forEach((a, i) => {
        particles.slice(i + 1).forEach(b => {
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < 120) {
            ctx.beginPath();
            ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
            ctx.strokeStyle = `rgba(56,182,255,${0.08 * (1 - d / 120)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        });
      });
      raf = requestAnimationFrame(draw);
    }
    draw();
    const resize = () => {
      w = canvas.width = window.innerWidth;
      h = canvas.height = window.innerHeight;
    };
    window.addEventListener("resize", resize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, []);
  return <canvas ref={canvasRef} style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none", opacity: 0.7 }} />;
}

// ── GRID OVERLAY ───────────────────────────────────────────────────────────
function GridOverlay() {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none",
      backgroundImage: `
        linear-gradient(rgba(56,182,255,0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(56,182,255,0.03) 1px, transparent 1px)
      `,
      backgroundSize: "60px 60px",
    }} />
  );
}

// ── NAV ────────────────────────────────────────────────────────────────────
function Nav({ page, setPage }) {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    const h = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", h);
    return () => window.removeEventListener("scroll", h);
  }, []);

  const links = [
    { id: "home", label: "Acasă" },
    { id: "about", label: "Despre Noi" },
    { id: "app", label: "Testează Strategia" },
    { id: "contact", label: "Contact" },
  ];

  return (
    <nav style={{
      position: "fixed", top: 0, left: 0, right: 0, zIndex: 100,
      padding: "0 2rem",
      background: scrolled
        ? "rgba(5,8,16,0.92)"
        : "transparent",
      backdropFilter: scrolled ? "blur(20px)" : "none",
      borderBottom: scrolled ? "1px solid rgba(56,182,255,0.1)" : "none",
      transition: "all 0.4s ease",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      height: "70px",
    }}>
      {/* Logo */}
      <div
        onClick={() => setPage("home")}
        style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer" }}
      >
        <div style={{
          width: 36, height: 36, borderRadius: "8px",
          background: "linear-gradient(135deg, #38b6ff, #0066cc)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontWeight: 900, fontSize: 16, color: "white", letterSpacing: "-1px",
          boxShadow: "0 0 16px rgba(56,182,255,0.4)",
        }}>LU</div>
        <span style={{
          fontFamily: "'Syne', sans-serif",
          fontWeight: 800, fontSize: 18, color: "white", letterSpacing: "0.5px",
        }}>LvlUp <span style={{ color: "#38b6ff" }}>Trading</span></span>
      </div>

      {/* Desktop links */}
      <div style={{ display: "flex", gap: "2rem", alignItems: "center" }}>
        {links.map(l => (
          <button key={l.id} onClick={() => setPage(l.id)} style={{
            background: "none", border: "none", cursor: "pointer",
            fontFamily: "'DM Sans', sans-serif",
            fontSize: 14, fontWeight: 500, letterSpacing: "0.3px",
            color: page === l.id ? "#38b6ff" : "rgba(255,255,255,0.65)",
            transition: "color 0.2s",
            padding: "4px 0",
            borderBottom: page === l.id ? "1px solid #38b6ff" : "1px solid transparent",
          }}>{l.label}</button>
        ))}
        <button onClick={() => setPage("app")} style={{
          background: "linear-gradient(135deg, #38b6ff, #0066cc)",
          border: "none", borderRadius: "8px", cursor: "pointer",
          padding: "8px 20px",
          fontFamily: "'DM Sans', sans-serif",
          fontSize: 13, fontWeight: 700, color: "white",
          boxShadow: "0 0 20px rgba(56,182,255,0.3)",
          transition: "transform 0.2s, box-shadow 0.2s",
        }}
          onMouseOver={e => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "0 4px 24px rgba(56,182,255,0.5)"; }}
          onMouseOut={e => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "0 0 20px rgba(56,182,255,0.3)"; }}
        >Start Gratuit →</button>
      </div>
    </nav>
  );
}

// ── SECTION WRAPPER cu fade-in la scroll ──────────────────────────────────
function Section({ children, style = {}, delay = 0 }) {
  const [ref, visible] = useInView();
  return (
    <div ref={ref} style={{
      opacity: visible ? 1 : 0,
      transform: visible ? "translateY(0)" : "translateY(40px)",
      transition: `opacity 0.7s ease ${delay}s, transform 0.7s ease ${delay}s`,
      ...style,
    }}>
      {children}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// PAGE: HOME
// ══════════════════════════════════════════════════════════════════════════
function HomePage({ setPage }) {
  const features = [
    {
      icon: "📊",
      title: "Analiză Completă",
      desc: "Statistici detaliate pe ore, minute, zile, luni și ani. Win rate, Profit Factor, R:R — tot ce ai nevoie.",
    },
    {
      icon: "🎲",
      title: "Monte Carlo",
      desc: "Simulează mii de scenarii aleatorii bazate pe istoricul tău real. Testează robustețea strategiei.",
    },
    {
      icon: "💰",
      title: "Risk Management",
      desc: "Kelly Criterion, Fixed Fractional Risk, analiza drawdown. Gestionează riscul ca un profesionist.",
    },
    {
      icon: "📈",
      title: "Payout Simulator",
      desc: "Calculează câștigurile pe cicluri de payout pentru 1–10 conturi funded simultan.",
    },
    {
      icon: "🔬",
      title: "Analize Avansate",
      desc: "Detectare overtrading, corelații între trade-uri, benchmark vs SPY Buy & Hold.",
    },
    {
      icon: "📄",
      title: "Export PDF",
      desc: "Raport complet cu toate graficele și statisticile, gata de partajat sau arhivat.",
    },
  ];

  const stats = [
    { value: 2400, suffix: "+", label: "Traderi Activi" },
    { value: 98, suffix: "%", label: "Acuratețe Date" },
    { value: 15000, suffix: "+", label: "Strategii Analizate" },
    { value: 4.9, suffix: "/5", label: "Rating Mediu" },
  ];

  const testimonials = [
    {
      name: "Alexandru M.",
      role: "Prop Trader — FTMO",
      text: "Am reușit să-mi cresc win rate-ul cu 12% în 3 luni după ce am văzut exact la ce ore tranzacționez cel mai bine. Unealta asta e game changer.",
      stars: 5,
    },
    {
      name: "Raluca P.",
      role: "Day Trader — Forex",
      text: "Simularea Monte Carlo m-a convins să reduc riscul per trade. Contul meu funded a supraviețuit o lună întreagă fără să ating daily DD-ul.",
      stars: 5,
    },
    {
      name: "Mihai D.",
      role: "Swing Trader",
      text: "PDF-ul exportat e perfect pentru a prezenta performanța la firmele de prop trading. Arată foarte profesional.",
      stars: 5,
    },
  ];

  return (
    <div style={{ paddingTop: "70px" }}>
      {/* ── HERO ── */}
      <div style={{
        minHeight: "100vh", display: "flex", alignItems: "center",
        justifyContent: "center", flexDirection: "column",
        textAlign: "center", padding: "0 2rem",
        position: "relative",
      }}>
        {/* Glow blob */}
        <div style={{
          position: "absolute", top: "30%", left: "50%", transform: "translate(-50%,-50%)",
          width: 600, height: 600, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(56,182,255,0.08) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />

        <div style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          background: "rgba(56,182,255,0.08)", border: "1px solid rgba(56,182,255,0.2)",
          borderRadius: 100, padding: "6px 16px", marginBottom: "1.5rem",
          animation: "fadeDown 0.6s ease both",
        }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#38b6ff", display: "inline-block", animation: "pulse 2s infinite" }} />
          <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: "#38b6ff", letterSpacing: "1px", textTransform: "uppercase", fontWeight: 600 }}>
            Platform Analiza Trading
          </span>
        </div>

        <h1 style={{
          fontFamily: "'Syne', sans-serif",
          fontSize: "clamp(2.8rem, 7vw, 5.5rem)",
          fontWeight: 900, lineHeight: 1.05,
          color: "white", margin: "0 0 1.2rem",
          animation: "fadeUp 0.7s ease 0.1s both",
          maxWidth: 800,
        }}>
          Transformă-ți{" "}
          <span style={{
            background: "linear-gradient(135deg, #38b6ff, #7dd3fc)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>Datele</span>
          {" "}în{" "}
          <span style={{
            background: "linear-gradient(135deg, #00e5a0, #38b6ff)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>Edge</span>
        </h1>

        <p style={{
          fontFamily: "'DM Sans', sans-serif",
          fontSize: "clamp(1rem, 2vw, 1.2rem)",
          color: "rgba(255,255,255,0.55)", maxWidth: 580,
          lineHeight: 1.7, margin: "0 0 2.5rem",
          animation: "fadeUp 0.7s ease 0.2s both",
        }}>
          Importă istoricul tău de trade-uri din TradingView și descoperă exact
          când, cum și de ce câștigi — sau pierzi. Analiză profesională în câteva secunde.
        </p>

        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", justifyContent: "center", animation: "fadeUp 0.7s ease 0.3s both" }}>
          <button onClick={() => setPage("app")} style={{
            background: "linear-gradient(135deg, #38b6ff, #0066cc)",
            border: "none", borderRadius: "12px", cursor: "pointer",
            padding: "14px 32px",
            fontFamily: "'Syne', sans-serif",
            fontSize: 15, fontWeight: 700, color: "white",
            boxShadow: "0 0 32px rgba(56,182,255,0.35)",
            transition: "all 0.2s",
          }}
            onMouseOver={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 40px rgba(56,182,255,0.5)"; }}
            onMouseOut={e => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "0 0 32px rgba(56,182,255,0.35)"; }}
          >
            🚀 Testează Gratuit
          </button>
          <button onClick={() => setPage("about")} style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "12px", cursor: "pointer",
            padding: "14px 32px",
            fontFamily: "'DM Sans', sans-serif",
            fontSize: 15, fontWeight: 500, color: "rgba(255,255,255,0.8)",
            transition: "all 0.2s",
          }}
            onMouseOver={e => { e.currentTarget.style.background = "rgba(255,255,255,0.08)"; e.currentTarget.style.borderColor = "rgba(56,182,255,0.3)"; }}
            onMouseOut={e => { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; e.currentTarget.style.borderColor = "rgba(255,255,255,0.12)"; }}
          >
            Despre Noi →
          </button>
        </div>

        {/* Scroll indicator */}
        <div style={{
          position: "absolute", bottom: "2rem", left: "50%", transform: "translateX(-50%)",
          display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
          animation: "bounce 2s infinite",
        }}>
          <span style={{ fontSize: 11, color: "rgba(255,255,255,0.3)", fontFamily: "'DM Sans', sans-serif", letterSpacing: "1px" }}>SCROLL</span>
          <div style={{ width: 1, height: 40, background: "linear-gradient(to bottom, rgba(56,182,255,0.6), transparent)" }} />
        </div>
      </div>

      {/* ── STATS ── */}
      <div style={{ padding: "5rem 2rem", position: "relative" }}>
        <div style={{
          maxWidth: 1100, margin: "0 auto",
          display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "2px",
          background: "rgba(56,182,255,0.08)", borderRadius: 20,
          border: "1px solid rgba(56,182,255,0.12)",
          overflow: "hidden",
        }}>
          {stats.map((s, i) => (
            <Section key={i} delay={i * 0.1}>
              <div style={{
                padding: "2.5rem 2rem", textAlign: "center",
                background: "rgba(5,8,16,0.6)",
                borderRight: i < stats.length - 1 ? "1px solid rgba(56,182,255,0.08)" : "none",
              }}>
                <div style={{
                  fontFamily: "'Syne', sans-serif", fontWeight: 900,
                  fontSize: "2.8rem", color: "#38b6ff",
                  marginBottom: 6,
                }}>
                  <Counter end={typeof s.value === "number" && s.value % 1 !== 0 ? s.value * 10 : s.value}
                    suffix={s.suffix}
                    duration={1800}
                  />
                </div>
                <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 13, color: "rgba(255,255,255,0.45)", letterSpacing: "0.5px" }}>
                  {s.label}
                </div>
              </div>
            </Section>
          ))}
        </div>
      </div>

      {/* ── FEATURES ── */}
      <div style={{ padding: "5rem 2rem" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          <Section style={{ textAlign: "center", marginBottom: "3rem" }}>
            <div style={{
              display: "inline-block",
              background: "rgba(56,182,255,0.06)", border: "1px solid rgba(56,182,255,0.15)",
              borderRadius: 100, padding: "4px 14px", marginBottom: "1rem",
            }}>
              <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 11, color: "#38b6ff", letterSpacing: "1.5px", textTransform: "uppercase" }}>
                Funcționalități
              </span>
            </div>
            <h2 style={{
              fontFamily: "'Syne', sans-serif", fontSize: "clamp(1.8rem, 4vw, 2.8rem)",
              fontWeight: 800, color: "white", margin: "0 0 0.8rem",
            }}>
              Tot ce ai nevoie pentru a{" "}
              <span style={{ color: "#38b6ff" }}>înțelege</span> strategia ta
            </h2>
            <p style={{ fontFamily: "'DM Sans', sans-serif", color: "rgba(255,255,255,0.45)", fontSize: 16, maxWidth: 500, margin: "0 auto" }}>
              Analiză completă, vizualizări clare, recomandări acționabile.
            </p>
          </Section>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "1.5px", background: "rgba(56,182,255,0.06)", borderRadius: 20, overflow: "hidden", border: "1px solid rgba(56,182,255,0.08)" }}>
            {features.map((f, i) => (
              <Section key={i} delay={i * 0.08}>
                <div
                  style={{
                    padding: "2rem",
                    background: "rgba(5,8,16,0.7)",
                    transition: "background 0.3s",
                    height: "100%", boxSizing: "border-box",
                  }}
                  onMouseOver={e => e.currentTarget.style.background = "rgba(56,182,255,0.05)"}
                  onMouseOut={e => e.currentTarget.style.background = "rgba(5,8,16,0.7)"}
                >
                  <div style={{ fontSize: 28, marginBottom: "0.8rem" }}>{f.icon}</div>
                  <h3 style={{
                    fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 17,
                    color: "white", margin: "0 0 0.5rem",
                  }}>{f.title}</h3>
                  <p style={{
                    fontFamily: "'DM Sans', sans-serif", fontSize: 14,
                    color: "rgba(255,255,255,0.45)", lineHeight: 1.7, margin: 0,
                  }}>{f.desc}</p>
                </div>
              </Section>
            ))}
          </div>
        </div>
      </div>

      {/* ── HOW IT WORKS ── */}
      <div style={{ padding: "5rem 2rem" }}>
        <div style={{ maxWidth: 900, margin: "0 auto", textAlign: "center" }}>
          <Section style={{ marginBottom: "3rem" }}>
            <h2 style={{
              fontFamily: "'Syne', sans-serif", fontSize: "clamp(1.8rem, 4vw, 2.8rem)",
              fontWeight: 800, color: "white", margin: "0 0 0.8rem",
            }}>
              3 pași simpli
            </h2>
            <p style={{ fontFamily: "'DM Sans', sans-serif", color: "rgba(255,255,255,0.45)", fontSize: 15 }}>
              De la date brute la insight-uri acționabile în mai puțin de un minut.
            </p>
          </Section>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "2rem" }}>
            {[
              { step: "01", title: "Exportă din TradingView", desc: "Descarcă fișierul XLSX cu istoricul tranzacțiilor tale direct din TradingView." },
              { step: "02", title: "Importă în Platformă", desc: "Drag & drop fișierul în aplicație. Procesarea e instantanee, fără configurare." },
              { step: "03", title: "Analizează & Optimizează", desc: "Explorează toate tab-urile, descoperă pattern-uri și exportă raportul PDF." },
            ].map((item, i) => (
              <Section key={i} delay={i * 0.15}>
                <div style={{ textAlign: "center", padding: "1.5rem" }}>
                  <div style={{
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    width: 56, height: 56, borderRadius: "50%",
                    background: "rgba(56,182,255,0.1)", border: "1px solid rgba(56,182,255,0.25)",
                    fontFamily: "'Syne', sans-serif", fontWeight: 900, fontSize: 14,
                    color: "#38b6ff", marginBottom: "1rem",
                  }}>{item.step}</div>
                  <h3 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 16, color: "white", margin: "0 0 0.5rem" }}>{item.title}</h3>
                  <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 13, color: "rgba(255,255,255,0.45)", lineHeight: 1.7, margin: 0 }}>{item.desc}</p>
                </div>
              </Section>
            ))}
          </div>
        </div>
      </div>

      {/* ── TESTIMONIALS ── */}
      <div style={{ padding: "5rem 2rem" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          <Section style={{ textAlign: "center", marginBottom: "3rem" }}>
            <h2 style={{
              fontFamily: "'Syne', sans-serif", fontSize: "clamp(1.8rem, 4vw, 2.8rem)",
              fontWeight: 800, color: "white", margin: "0 0 0.8rem",
            }}>
              Ce spun <span style={{ color: "#38b6ff" }}>traderii noștri</span>
            </h2>
          </Section>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(290px, 1fr))", gap: "1.5rem" }}>
            {testimonials.map((t, i) => (
              <Section key={i} delay={i * 0.12}>
                <div style={{
                  background: "rgba(255,255,255,0.03)",
                  border: "1px solid rgba(56,182,255,0.1)",
                  borderRadius: 16, padding: "1.8rem",
                  transition: "border-color 0.3s, transform 0.3s",
                }}
                  onMouseOver={e => { e.currentTarget.style.borderColor = "rgba(56,182,255,0.3)"; e.currentTarget.style.transform = "translateY(-4px)"; }}
                  onMouseOut={e => { e.currentTarget.style.borderColor = "rgba(56,182,255,0.1)"; e.currentTarget.style.transform = "none"; }}
                >
                  <div style={{ marginBottom: "1rem" }}>
                    {"★".repeat(t.stars).split("").map((s, j) => (
                      <span key={j} style={{ color: "#38b6ff", fontSize: 14 }}>{s}</span>
                    ))}
                  </div>
                  <p style={{
                    fontFamily: "'DM Sans', sans-serif", fontSize: 14, lineHeight: 1.75,
                    color: "rgba(255,255,255,0.65)", margin: "0 0 1.5rem", fontStyle: "italic",
                  }}>"{t.text}"</p>
                  <div>
                    <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 14, color: "white" }}>{t.name}</div>
                    <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: "#38b6ff", marginTop: 2 }}>{t.role}</div>
                  </div>
                </div>
              </Section>
            ))}
          </div>
        </div>
      </div>

      {/* ── CTA FINAL ── */}
      <div style={{ padding: "6rem 2rem" }}>
        <Section>
          <div style={{
            maxWidth: 700, margin: "0 auto", textAlign: "center",
            background: "linear-gradient(135deg, rgba(56,182,255,0.06), rgba(0,102,204,0.06))",
            border: "1px solid rgba(56,182,255,0.15)",
            borderRadius: 24, padding: "4rem 2rem",
            position: "relative", overflow: "hidden",
          }}>
            <div style={{
              position: "absolute", top: -80, right: -80, width: 300, height: 300,
              borderRadius: "50%",
              background: "radial-gradient(circle, rgba(56,182,255,0.08) 0%, transparent 70%)",
              pointerEvents: "none",
            }} />
            <h2 style={{
              fontFamily: "'Syne', sans-serif", fontSize: "clamp(1.8rem, 4vw, 2.5rem)",
              fontWeight: 900, color: "white", margin: "0 0 1rem",
            }}>
              Gata să-ți înțelegi strategia?
            </h2>
            <p style={{
              fontFamily: "'DM Sans', sans-serif", fontSize: 15,
              color: "rgba(255,255,255,0.5)", margin: "0 0 2rem", lineHeight: 1.7,
            }}>
              Importă primul tău fișier gratuit și descoperă insight-uri pe care nu le știai.
            </p>
            <button onClick={() => setPage("app")} style={{
              background: "linear-gradient(135deg, #38b6ff, #0066cc)",
              border: "none", borderRadius: "12px", cursor: "pointer",
              padding: "14px 36px",
              fontFamily: "'Syne', sans-serif",
              fontSize: 15, fontWeight: 700, color: "white",
              boxShadow: "0 0 40px rgba(56,182,255,0.3)",
              transition: "all 0.2s",
            }}
              onMouseOver={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 40px rgba(56,182,255,0.5)"; }}
              onMouseOut={e => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "0 0 40px rgba(56,182,255,0.3)"; }}
            >
              🚀 Începe Analiza — Gratuit
            </button>
          </div>
        </Section>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// PAGE: ABOUT
// ══════════════════════════════════════════════════════════════════════════
function AboutPage() {
  const values = [
    { icon: "🎯", title: "Precizie", desc: "Fiecare statistică e calculată exact, fără aproximări. Datele tale merită acuratețe 100%." },
    { icon: "🔒", title: "Privat", desc: "Datele tale rămân în browser. Nu stocăm niciun trade, nicio strategie, nicio informație personală." },
    { icon: "⚡", title: "Viteză", desc: "Analiză completă în secunde, indiferent de câte mii de trade-uri ai în fișier." },
    { icon: "🧠", title: "Inteligent", desc: "Algoritmi avansați: Monte Carlo, Kelly Criterion, detecție overtrading, corelații între trades." },
  ];

  return (
    <div style={{ paddingTop: "70px" }}>
      {/* Hero */}
      <div style={{ padding: "6rem 2rem 3rem", maxWidth: 900, margin: "0 auto", textAlign: "center" }}>
        <Section>
          <div style={{
            display: "inline-block",
            background: "rgba(56,182,255,0.06)", border: "1px solid rgba(56,182,255,0.15)",
            borderRadius: 100, padding: "4px 14px", marginBottom: "1.5rem",
          }}>
            <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 11, color: "#38b6ff", letterSpacing: "1.5px", textTransform: "uppercase" }}>
              Despre Noi
            </span>
          </div>
          <h1 style={{
            fontFamily: "'Syne', sans-serif", fontSize: "clamp(2rem, 5vw, 3.5rem)",
            fontWeight: 900, color: "white", margin: "0 0 1.5rem", lineHeight: 1.1,
          }}>
            Construiți de traderi,{" "}
            <span style={{ color: "#38b6ff" }}>pentru traderi</span>
          </h1>
          <p style={{
            fontFamily: "'DM Sans', sans-serif", fontSize: 17,
            color: "rgba(255,255,255,0.5)", lineHeight: 1.8, maxWidth: 650, margin: "0 auto",
          }}>
            LvlUp Trading s-a născut dintr-o problemă reală: analiza manuală a sute de trade-uri
            este lentă, obositoare și adesea inexactă. Am construit instrumentul pe care noi înșine
            îl voiam — și l-am oferit comunității.
          </p>
        </Section>
      </div>

      {/* Mission */}
      <div style={{ padding: "3rem 2rem", maxWidth: 1100, margin: "0 auto" }}>
        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4rem",
          alignItems: "center",
        }}>
          <Section>
            <div style={{
              background: "linear-gradient(135deg, rgba(56,182,255,0.06), rgba(0,102,204,0.04))",
              border: "1px solid rgba(56,182,255,0.1)",
              borderRadius: 20, padding: "3rem",
            }}>
              <h2 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 24, color: "white", margin: "0 0 1rem" }}>
                Misiunea noastră
              </h2>
              <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 15, color: "rgba(255,255,255,0.55)", lineHeight: 1.8, margin: 0 }}>
                Să democratizăm analiza profesională de trading. Instrumentele pe care le folosesc
                firmele mari de prop trading să fie accesibile oricărui trader independent,
                indiferent de experiență sau buget.
              </p>
            </div>
          </Section>
          <Section delay={0.15}>
            <div style={{
              background: "linear-gradient(135deg, rgba(0,229,160,0.04), rgba(56,182,255,0.04))",
              border: "1px solid rgba(0,229,160,0.1)",
              borderRadius: 20, padding: "3rem",
            }}>
              <h2 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 24, color: "white", margin: "0 0 1rem" }}>
                Viziunea noastră
              </h2>
              <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 15, color: "rgba(255,255,255,0.55)", lineHeight: 1.8, margin: 0 }}>
                Un ecosistem complet în care orice trader poate analiza, optimiza și scala
                strategia lui cu încredere — susținut de date reale, nu instincte.
              </p>
            </div>
          </Section>
        </div>
      </div>

      {/* Values */}
      <div style={{ padding: "5rem 2rem" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          <Section style={{ textAlign: "center", marginBottom: "3rem" }}>
            <h2 style={{ fontFamily: "'Syne', sans-serif", fontSize: "clamp(1.6rem, 3vw, 2.2rem)", fontWeight: 800, color: "white", margin: 0 }}>
              Valorile noastre
            </h2>
          </Section>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: "1.5rem" }}>
            {values.map((v, i) => (
              <Section key={i} delay={i * 0.1}>
                <div style={{
                  background: "rgba(255,255,255,0.02)", border: "1px solid rgba(56,182,255,0.08)",
                  borderRadius: 16, padding: "2rem",
                  transition: "all 0.3s",
                }}
                  onMouseOver={e => { e.currentTarget.style.background = "rgba(56,182,255,0.04)"; e.currentTarget.style.borderColor = "rgba(56,182,255,0.25)"; }}
                  onMouseOut={e => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; e.currentTarget.style.borderColor = "rgba(56,182,255,0.08)"; }}
                >
                  <div style={{ fontSize: 28, marginBottom: "0.8rem" }}>{v.icon}</div>
                  <h3 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 17, color: "white", margin: "0 0 0.5rem" }}>{v.title}</h3>
                  <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 13, color: "rgba(255,255,255,0.45)", lineHeight: 1.7, margin: 0 }}>{v.desc}</p>
                </div>
              </Section>
            ))}
          </div>
        </div>
      </div>

      {/* Team placeholder */}
      <div style={{ padding: "3rem 2rem 6rem" }}>
        <div style={{ maxWidth: 800, margin: "0 auto", textAlign: "center" }}>
          <Section>
            <div style={{
              background: "rgba(56,182,255,0.04)",
              border: "1px dashed rgba(56,182,255,0.2)",
              borderRadius: 20, padding: "3rem",
            }}>
              <div style={{ fontSize: 40, marginBottom: "1rem" }}>👥</div>
              <h3 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 20, color: "white", margin: "0 0 0.5rem" }}>
                Echipa LvlUp
              </h3>
              <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 14, color: "rgba(255,255,255,0.4)", margin: 0 }}>
                Secțiunea echipei vine în curând. Adaugă membrii tăi din pagina Contact.
              </p>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// PAGE: APP (embed Streamlit)
// ══════════════════════════════════════════════════════════════════════════
function AppPage() {
  const STREAMLIT_URL = "http://localhost:8501";
  return (
    <div style={{ paddingTop: "70px", minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "2rem 2rem 1rem", textAlign: "center" }}>
        <Section>
          <h1 style={{
            fontFamily: "'Syne', sans-serif", fontWeight: 900,
            fontSize: "clamp(1.8rem, 4vw, 2.8rem)", color: "white", margin: "0 0 0.5rem",
          }}>
            Testează-ți <span style={{ color: "#38b6ff" }}>Strategia</span>
          </h1>
          <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 14, color: "rgba(255,255,255,0.4)", margin: "0 0 1rem" }}>
            Importă fișierul XLSX din TradingView și obține analiza completă instant.
          </p>
          <a href={STREAMLIT_URL} target="_blank" rel="noopener noreferrer" style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            background: "rgba(56,182,255,0.08)", border: "1px solid rgba(56,182,255,0.2)",
            borderRadius: 8, padding: "6px 14px",
            fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: "#38b6ff",
            textDecoration: "none", marginBottom: "1.5rem",
          }}>
            ↗ Deschide în tab nou
          </a>
        </Section>
      </div>
      <div style={{ flex: 1, padding: "0 1rem 2rem" }}>
        <iframe
          src={STREAMLIT_URL}
          style={{
            width: "100%", height: "calc(100vh - 220px)",
            border: "1px solid rgba(56,182,255,0.12)",
            borderRadius: 16, background: "#0e1117",
            minHeight: 600,
          }}
          title="LvlUp Trading App"
        />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// PAGE: CONTACT
// ══════════════════════════════════════════════════════════════════════════
function ContactPage() {
  const [sent, setSent] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", message: "" });

  const socials = [
    { icon: "📧", label: "Email", value: "contact@lvluptrading.ro" },
    { icon: "💬", label: "Discord", value: "discord.gg/lvluptrading" },
    { icon: "📱", label: "Instagram", value: "@lvluptrading" },
    { icon: "▶️", label: "YouTube", value: "LvlUp Trading" },
  ];

  return (
    <div style={{ paddingTop: "70px" }}>
      <div style={{ padding: "5rem 2rem", maxWidth: 1100, margin: "0 auto" }}>
        <Section style={{ textAlign: "center", marginBottom: "4rem" }}>
          <div style={{
            display: "inline-block",
            background: "rgba(56,182,255,0.06)", border: "1px solid rgba(56,182,255,0.15)",
            borderRadius: 100, padding: "4px 14px", marginBottom: "1.5rem",
          }}>
            <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 11, color: "#38b6ff", letterSpacing: "1.5px", textTransform: "uppercase" }}>
              Contact
            </span>
          </div>
          <h1 style={{
            fontFamily: "'Syne', sans-serif", fontSize: "clamp(2rem, 5vw, 3.2rem)",
            fontWeight: 900, color: "white", margin: "0 0 1rem",
          }}>
            Hai să <span style={{ color: "#38b6ff" }}>vorbim</span>
          </h1>
          <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 16, color: "rgba(255,255,255,0.45)", maxWidth: 500, margin: "0 auto" }}>
            Ai întrebări, sugestii sau vrei să colaborăm? Suntem aici.
          </p>
        </Section>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: "3rem", alignItems: "start" }}>
          {/* Socials */}
          <Section>
            <div>
              <h3 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 18, color: "white", margin: "0 0 1.5rem" }}>
                Găsește-ne pe
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                {socials.map((s, i) => (
                  <div key={i} style={{
                    display: "flex", alignItems: "center", gap: "1rem",
                    background: "rgba(255,255,255,0.02)", border: "1px solid rgba(56,182,255,0.08)",
                    borderRadius: 12, padding: "1rem 1.2rem",
                    transition: "all 0.2s",
                  }}
                    onMouseOver={e => { e.currentTarget.style.background = "rgba(56,182,255,0.05)"; e.currentTarget.style.borderColor = "rgba(56,182,255,0.2)"; }}
                    onMouseOut={e => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; e.currentTarget.style.borderColor = "rgba(56,182,255,0.08)"; }}
                  >
                    <span style={{ fontSize: 20 }}>{s.icon}</span>
                    <div>
                      <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 11, color: "rgba(255,255,255,0.35)", letterSpacing: "0.5px", marginBottom: 2 }}>{s.label}</div>
                      <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 14, color: "rgba(255,255,255,0.8)", fontWeight: 500 }}>{s.value}</div>
                    </div>
                  </div>
                ))}
              </div>

              {/* Team placeholder */}
              <div style={{
                marginTop: "2rem",
                background: "rgba(56,182,255,0.04)",
                border: "1px dashed rgba(56,182,255,0.18)",
                borderRadius: 16, padding: "1.5rem", textAlign: "center",
              }}>
                <div style={{ fontSize: 28, marginBottom: 8 }}>👥</div>
                <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 13, color: "rgba(255,255,255,0.35)", margin: 0, lineHeight: 1.6 }}>
                  <span style={{ color: "rgba(255,255,255,0.6)", fontWeight: 600 }}>Zona Echipă</span><br />
                  Adaugă membrii echipei tale aici.
                </p>
              </div>
            </div>
          </Section>

          {/* Contact form */}
          <Section delay={0.15}>
            <div style={{
              background: "rgba(255,255,255,0.02)", border: "1px solid rgba(56,182,255,0.1)",
              borderRadius: 20, padding: "2.5rem",
            }}>
              {sent ? (
                <div style={{ textAlign: "center", padding: "2rem 0" }}>
                  <div style={{ fontSize: 48, marginBottom: "1rem" }}>✅</div>
                  <h3 style={{ fontFamily: "'Syne', sans-serif", color: "#38b6ff", fontWeight: 700 }}>Mesaj trimis!</h3>
                  <p style={{ fontFamily: "'DM Sans', sans-serif", color: "rgba(255,255,255,0.5)", fontSize: 14 }}>
                    Îți vom răspunde în cel mai scurt timp.
                  </p>
                  <button onClick={() => setSent(false)} style={{
                    background: "none", border: "1px solid rgba(56,182,255,0.3)",
                    borderRadius: 8, color: "#38b6ff", cursor: "pointer",
                    fontFamily: "'DM Sans', sans-serif", fontSize: 13, padding: "8px 20px", marginTop: "1rem",
                  }}>Trimite alt mesaj</button>
                </div>
              ) : (
                <>
                  <h3 style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 18, color: "white", margin: "0 0 1.5rem" }}>
                    Trimite un mesaj
                  </h3>
                  {[
                    { label: "Numele tău", key: "name", type: "text", placeholder: "Ion Popescu" },
                    { label: "Email", key: "email", type: "email", placeholder: "ion@email.com" },
                  ].map(field => (
                    <div key={field.key} style={{ marginBottom: "1.2rem" }}>
                      <label style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: "rgba(255,255,255,0.45)", display: "block", marginBottom: 6, letterSpacing: "0.5px" }}>
                        {field.label.toUpperCase()}
                      </label>
                      <input
                        type={field.type}
                        placeholder={field.placeholder}
                        value={form[field.key]}
                        onChange={e => setForm(f => ({ ...f, [field.key]: e.target.value }))}
                        style={{
                          width: "100%", boxSizing: "border-box",
                          background: "rgba(255,255,255,0.04)", border: "1px solid rgba(56,182,255,0.12)",
                          borderRadius: 10, padding: "10px 14px",
                          fontFamily: "'DM Sans', sans-serif", fontSize: 14,
                          color: "white", outline: "none",
                          transition: "border-color 0.2s",
                        }}
                        onFocus={e => e.target.style.borderColor = "rgba(56,182,255,0.4)"}
                        onBlur={e => e.target.style.borderColor = "rgba(56,182,255,0.12)"}
                      />
                    </div>
                  ))}
                  <div style={{ marginBottom: "1.5rem" }}>
                    <label style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: "rgba(255,255,255,0.45)", display: "block", marginBottom: 6, letterSpacing: "0.5px" }}>
                      MESAJ
                    </label>
                    <textarea
                      placeholder="Scrie mesajul tău..."
                      value={form.message}
                      onChange={e => setForm(f => ({ ...f, message: e.target.value }))}
                      rows={5}
                      style={{
                        width: "100%", boxSizing: "border-box", resize: "vertical",
                        background: "rgba(255,255,255,0.04)", border: "1px solid rgba(56,182,255,0.12)",
                        borderRadius: 10, padding: "10px 14px",
                        fontFamily: "'DM Sans', sans-serif", fontSize: 14,
                        color: "white", outline: "none",
                        transition: "border-color 0.2s",
                      }}
                      onFocus={e => e.target.style.borderColor = "rgba(56,182,255,0.4)"}
                      onBlur={e => e.target.style.borderColor = "rgba(56,182,255,0.12)"}
                    />
                  </div>
                  <button onClick={() => setSent(true)} style={{
                    width: "100%",
                    background: "linear-gradient(135deg, #38b6ff, #0066cc)",
                    border: "none", borderRadius: 10, cursor: "pointer",
                    padding: "12px",
                    fontFamily: "'Syne', sans-serif", fontSize: 14, fontWeight: 700, color: "white",
                    boxShadow: "0 0 24px rgba(56,182,255,0.25)",
                    transition: "all 0.2s",
                  }}
                    onMouseOver={e => { e.currentTarget.style.boxShadow = "0 4px 32px rgba(56,182,255,0.45)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                    onMouseOut={e => { e.currentTarget.style.boxShadow = "0 0 24px rgba(56,182,255,0.25)"; e.currentTarget.style.transform = "none"; }}
                  >
                    Trimite Mesajul →
                  </button>
                </>
              )}
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

// ── FOOTER ─────────────────────────────────────────────────────────────────
function Footer({ setPage }) {
  return (
    <footer style={{
      borderTop: "1px solid rgba(56,182,255,0.08)",
      padding: "3rem 2rem",
      textAlign: "center",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "10px", marginBottom: "1rem" }}>
        <div style={{
          width: 28, height: 28, borderRadius: "6px",
          background: "linear-gradient(135deg, #38b6ff, #0066cc)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontWeight: 900, fontSize: 12, color: "white",
        }}>LU</div>
        <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 15, color: "rgba(255,255,255,0.6)" }}>
          LvlUp Trading
        </span>
      </div>
      <div style={{ display: "flex", justifyContent: "center", gap: "2rem", marginBottom: "1.5rem", flexWrap: "wrap" }}>
        {[["home","Acasă"], ["about","Despre Noi"], ["app","Testează"], ["contact","Contact"]].map(([id, label]) => (
          <button key={id} onClick={() => setPage(id)} style={{
            background: "none", border: "none", cursor: "pointer",
            fontFamily: "'DM Sans', sans-serif", fontSize: 13,
            color: "rgba(255,255,255,0.35)",
            transition: "color 0.2s",
          }}
            onMouseOver={e => e.currentTarget.style.color = "#38b6ff"}
            onMouseOut={e => e.currentTarget.style.color = "rgba(255,255,255,0.35)"}
          >{label}</button>
        ))}
      </div>
      <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: "rgba(255,255,255,0.2)", margin: 0 }}>
        © 2025 LvlUp Trading. Toate drepturile rezervate.
      </p>
    </footer>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// ROOT APP
// ══════════════════════════════════════════════════════════════════════════
export default function App() {
  const [page, setPage] = useState("home");
  const [transitioning, setTransitioning] = useState(false);
  const prevPage = useRef("home");

  function navigate(newPage) {
    if (newPage === page) return;
    setTransitioning(true);
    setTimeout(() => {
      prevPage.current = page;
      setPage(newPage);
      setTransitioning(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }, 250);
  }

  const pageMap = {
    home: <HomePage setPage={navigate} />,
    about: <AboutPage />,
    app: <AppPage />,
    contact: <ContactPage />,
  };

  return (
    <>
      {/* Google Fonts */}
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800;900&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />

      <style>{`
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html { scroll-behavior: smooth; }
        body { background: #050810; color: white; overflow-x: hidden; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #050810; }
        ::-webkit-scrollbar-thumb { background: rgba(56,182,255,0.3); border-radius: 2px; }

        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(30px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes fadeDown {
          from { opacity: 0; transform: translateY(-20px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes bounce {
          0%, 100% { transform: translateX(-50%) translateY(0); }
          50% { transform: translateX(-50%) translateY(8px); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }

        input::placeholder, textarea::placeholder { color: rgba(255,255,255,0.2); }
        input, textarea { background-color: rgba(255,255,255,0.04) !important; }
      `}</style>

      <div style={{ minHeight: "100vh", background: "#050810", position: "relative" }}>
        <GridOverlay />
        <ParticleCanvas />

        <div style={{ position: "relative", zIndex: 1 }}>
          <Nav page={page} setPage={navigate} />

          {/* Page transition */}
          <div style={{
            opacity: transitioning ? 0 : 1,
            transform: transitioning ? "translateY(12px)" : "translateY(0)",
            transition: "opacity 0.25s ease, transform 0.25s ease",
          }}>
            {pageMap[page]}
          </div>

          <Footer setPage={navigate} />
        </div>
      </div>
    </>
  );
}
