import { useState, useMemo } from "react";

// ─── Data: speglar SQL-schemat (flat lista med foralder_id) ───────────────
const FUNKTIONER = [
  { id: 1,  namn: "Publicering", typ: "förmåga", status: "befintlig", fas: "nu", foralder: null },
  { id: 2,  namn: "Registrera avhandling", typ: "funktion", status: "befintlig", fas: "nu", foralder: 1 },
  { id: 3,  namn: "Spikblad genereras automatiskt", typ: "krav", status: "planerad", fas: "nästa", foralder: 2 },
  { id: 4,  namn: "ORCID valideras vid inmatning", typ: "krav", status: "befintlig", fas: "nu", foralder: 2 },
  { id: 5,  namn: "DOI tilldelas alla publikationstyper", typ: "krav", status: "planerad", fas: "nästa", foralder: 1 },
  { id: 6,  namn: "Import", typ: "funktion", status: "befintlig", fas: "nu", foralder: 1 },
  { id: 7,  namn: "Import från Web of Science", typ: "funktion", status: "planerad", fas: "senare", foralder: 6 },
  { id: 8,  namn: "Dubblettdetektering vid import", typ: "krav", status: "idé", fas: "senare", foralder: 7 },
  { id: 9,  namn: "BibTeX-import bevarar specialtecken", typ: "krav", status: "befintlig", fas: "nu", foralder: 6 },
  { id: 10, namn: "Export & spridning", typ: "förmåga", status: "befintlig", fas: "nu", foralder: null },
  { id: 11, namn: "OAI-PMH med borttagsspårning", typ: "krav", status: "planerad", fas: "nästa", foralder: 10 },
  { id: 12, namn: "Export till SwePub", typ: "funktion", status: "befintlig", fas: "nu", foralder: 10 },
  { id: 13, namn: "MODS-export följer kanoniskt format", typ: "krav", status: "planerad", fas: "nu", foralder: 12 },
  { id: 14, namn: "Administration", typ: "förmåga", status: "planerad", fas: "nästa", foralder: null },
  { id: 15, namn: "Behörighetsstyrning per organisationsenhet", typ: "krav", status: "planerad", fas: "nästa", foralder: 14 },
  { id: 16, namn: "Statistikuttag per institution", typ: "funktion", status: "idé", fas: "senare", foralder: 14 },
];

const MEDLEMMAR = [
  { id: 1, namn: "Uppsala universitet" },
  { id: 2, namn: "Högskolan i Gävle" },
  { id: 3, namn: "Kungliga Tekniska högskolan" },
  { id: 4, namn: "Naturhistoriska riksmuseet" },
  { id: 5, namn: "Umeå universitet" },
  { id: 6, namn: "Södertörns högskola" },
];

// Förifyllda bedömningar (proxy-inmatade från dialogmöten)
const START_BEDOMNINGAR = {
  "1-3": { svar: "golive", kommentar: "Rektorsbeslut kräver digitala spikblad fr.o.m. 2027." },
  "1-5": { svar: "golive" },
  "1-11": { svar: "kan_vanta", workaround: "Cron-skript som diffar mot gårdagens skörd och rapporterar borttag manuellt." },
  "2-3": { svar: "behovs_ej", kommentar: "Vi utfärdar inga doktorsexamina." },
  "2-5": { svar: "kan_vanta", workaround: "DOI mintas via Crossref-portalen tills vidare." },
  "2-15": { svar: "golive" },
  "3-5": { svar: "golive" },
  "3-8": { svar: "golive", kommentar: "Dubbletter är vårt största kvalitetsproblem idag." },
  "3-11": { svar: "golive" },
  "5-5": { svar: "golive" },
  "5-13": { svar: "kan_vanta", workaround: "Egen XSLT-transform i pipeline mot SwePub." },
};

const SVAR = {
  golive:    { label: "Ja, för go-live",    kort: "Go-live",  dot: "bg-rose-600",  pill: "bg-rose-600 text-white border-rose-600",  ghost: "text-rose-700 border-rose-200 hover:bg-rose-50" },
  kan_vanta: { label: "Ja, kan vänta 6–12 mån", kort: "Kan vänta", dot: "bg-amber-500", pill: "bg-amber-500 text-white border-amber-500", ghost: "text-amber-700 border-amber-200 hover:bg-amber-50" },
  behovs_ej: { label: "Behövs ej",          kort: "Behövs ej", dot: "bg-stone-400", pill: "bg-stone-500 text-white border-stone-500", ghost: "text-stone-500 border-stone-200 hover:bg-stone-100" },
};

const STATUS = {
  befintlig: { label: "Befintlig", cls: "bg-emerald-100 text-emerald-800" },
  planerad:  { label: "Planerad",  cls: "bg-sky-100 text-sky-800" },
  idé:       { label: "Idé",       cls: "bg-stone-200 text-stone-600" },
};

const TYP = {
  "förmåga":  "text-blue-900 font-semibold",
  "funktion": "text-stone-800 font-medium",
  "krav":     "text-stone-700",
};

// ─── Hjälpfunktioner (motsvarar de rekursiva CTE:erna) ────────────────────
const barnTill = (id) => FUNKTIONER.filter((f) => f.foralder === id);
const rotter = FUNKTIONER.filter((f) => f.foralder === null);
const byId = Object.fromEntries(FUNKTIONER.map((f) => [f.id, f]));

function effektivtSvar(bedomningar, medlemId, funkId) {
  // Eget svar, annars närmaste förälders (arvsregeln)
  let id = funkId;
  let arv = false;
  while (id != null) {
    const b = bedomningar[`${medlemId}-${id}`];
    if (b) return { ...b, arv, fran: byId[id] };
    id = byId[id].foralder;
    arv = true;
  }
  return null;
}

// ─── Komponenter ──────────────────────────────────────────────────────────
function Badge({ children, cls }) {
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs ${cls}`}>{children}</span>;
}

function Chevron({ open }) {
  return (
    <svg viewBox="0 0 16 16" className={`h-3.5 w-3.5 shrink-0 text-stone-400 transition-transform ${open ? "rotate-90" : ""}`} fill="currentColor">
      <path d="M6 3.5 11 8l-5 4.5v-9z" />
    </svg>
  );
}

function TradRad({ funk, djup, oppna, toggla, hoger }) {
  const barn = barnTill(funk.id);
  const open = oppna.has(funk.id);
  return (
    <>
      <div className="flex items-center gap-2 border-b border-stone-100 py-2 pr-2 hover:bg-stone-50" style={{ paddingLeft: `${djup * 22 + 8}px` }}>
        {barn.length > 0 ? (
          <button onClick={() => toggla(funk.id)} aria-label={open ? "Fäll ihop" : "Fäll ut"} className="rounded p-0.5 focus:outline-none focus:ring-2 focus:ring-blue-700">
            <Chevron open={open} />
          </button>
        ) : (
          <span className="w-[18px] shrink-0" />
        )}
        <span className={`min-w-0 flex-1 truncate text-sm ${TYP[funk.typ]}`}>{funk.namn}</span>
        {hoger(funk)}
      </div>
      {open && barn.map((b) => <TradRad key={b.id} funk={b} djup={djup + 1} oppna={oppna} toggla={toggla} hoger={hoger} />)}
    </>
  );
}

function Trad({ hoger, forvalda }) {
  const [oppna, setOppna] = useState(new Set(forvalda ?? FUNKTIONER.map((f) => f.id)));
  const toggla = (id) =>
    setOppna((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  return (
    <div className="rounded-lg border border-stone-200 bg-white">
      {rotter.map((r) => (
        <TradRad key={r.id} funk={r} djup={0} oppna={oppna} toggla={toggla} hoger={hoger} />
      ))}
    </div>
  );
}

// ─── Vy 1: Kravträd (admin) ───────────────────────────────────────────────
function VyTrad() {
  return (
    <>
      <p className="mb-3 text-sm text-stone-500">
        Hela hierarkin. Typ är en etikett — krav kan ligga på vilken nivå som helst.
      </p>
      <Trad
        hoger={(f) => (
          <span className="flex shrink-0 items-center gap-1.5">
            <Badge cls="bg-stone-100 text-stone-500">{f.typ}</Badge>
            <Badge cls={STATUS[f.status].cls}>{STATUS[f.status].label}</Badge>
            <span className="hidden w-14 text-right text-xs text-stone-400 sm:inline">{f.fas}</span>
          </span>
        )}
      />
    </>
  );
}

// ─── Vy 2: Bedömning (medlem) ─────────────────────────────────────────────
function VyBedomning({ bedomningar, setBedomningar }) {
  const [medlem, setMedlem] = useState(2);
  const [kommentarOppen, setKommentarOppen] = useState(new Set());

  const satt = (funkId, falt, varde) =>
    setBedomningar((b) => {
      const k = `${medlem}-${funkId}`;
      const rad = { ...(b[k] ?? {}) };
      if (falt === "svar" && rad.svar === varde) {
        const { [k]: _, ...rest } = b; // klicka igen = ta bort svaret
        return rest;
      }
      rad[falt] = varde;
      return { ...b, [k]: rad };
    });

  const togglaKommentar = (id) =>
    setKommentarOppen((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label htmlFor="medlem" className="text-sm text-stone-600">Svarar som:</label>
        <select
          id="medlem"
          value={medlem}
          onChange={(e) => setMedlem(Number(e.target.value))}
          className="rounded-md border border-stone-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-700"
        >
          {MEDLEMMAR.map((m) => (
            <option key={m.id} value={m.id}>{m.namn}</option>
          ))}
        </select>
      </div>

      <Trad
        hoger={(f) => {
          const k = `${medlem}-${f.id}`;
          const eget = bedomningar[k];
          const eff = !eget && effektivtSvar(bedomningar, medlem, f.id);
          return (
            <span className="flex shrink-0 flex-col items-end gap-1">
              <span className="flex items-center gap-1">
                {Object.entries(SVAR).map(([key, s]) => (
                  <button
                    key={key}
                    onClick={() => satt(f.id, "svar", key)}
                    title={s.label}
                    className={`rounded-full border px-2 py-0.5 text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-blue-700 ${
                      eget?.svar === key ? s.pill : s.ghost
                    }`}
                  >
                    {s.kort}
                  </button>
                ))}
                <button
                  onClick={() => togglaKommentar(f.id)}
                  title="Kommentar"
                  className={`ml-1 rounded-full border px-2 py-0.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-700 ${
                    eget?.kommentar ? "border-blue-300 bg-blue-50 text-blue-800" : "border-stone-200 text-stone-400 hover:bg-stone-100"
                  }`}
                >
                  💬
                </button>
              </span>
              {eff?.svar && (
                <span className="text-[11px] italic text-stone-400">
                  ärvt: {SVAR[eff.svar].kort} (från {eff.fran.namn})
                </span>
              )}
              {eget?.svar === "kan_vanta" && (
                <input
                  value={eget.workaround ?? ""}
                  onChange={(e) => satt(f.id, "workaround", e.target.value)}
                  placeholder="Workaround: hur klarar ni er under tiden?"
                  className="w-64 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs placeholder-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-400"
                />
              )}
              {kommentarOppen.has(f.id) && (
                <input
                  value={eget?.kommentar ?? ""}
                  onChange={(e) => satt(f.id, "kommentar", e.target.value)}
                  placeholder="Kommentar till ert svar (privat)"
                  className="w-64 rounded border border-stone-200 px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-blue-700"
                />
              )}
            </span>
          );
        }}
      />
      <p className="mt-3 text-xs text-stone-400">
        Klicka på samma knapp igen för att ångra. Svar på en förälder ärvs av barnen tills något mer specifikt anges.
      </p>
    </>
  );
}

// ─── Vy 3: Analys ─────────────────────────────────────────────────────────
function VyAnalys({ bedomningar }) {
  const rader = useMemo(() => {
    return FUNKTIONER.map((f) => {
      const svar = MEDLEMMAR.map((m) => bedomningar[`${m.id}-${f.id}`]).filter(Boolean);
      const n = (t) => svar.filter((s) => s.svar === t).length;
      const workarounds = svar.filter((s) => s.workaround).map((s) => s.workaround);
      return { f, golive: n("golive"), kan_vanta: n("kan_vanta"), behovs_ej: n("behovs_ej"), workarounds };
    })
      .filter((r) => r.golive + r.kan_vanta + r.behovs_ej > 0)
      .sort((a, b) => b.golive - a.golive || b.kan_vanta - a.kan_vanta);
  }, [bedomningar]);

  const svarande = new Set(Object.keys(bedomningar).map((k) => k.split("-")[0])).size;
  const max = Math.max(1, ...rader.map((r) => r.golive + r.kan_vanta + r.behovs_ej));

  return (
    <>
      <p className="mb-3 text-sm text-stone-500">
        Blockerar-rankning · <strong>{svarande} av {MEDLEMMAR.length}</strong> medlemmar har lämnat svar — obesvarat är inte "nej".
      </p>
      <div className="space-y-2">
        {rader.map(({ f, golive, kan_vanta, behovs_ej, workarounds }) => {
          const tot = golive + kan_vanta + behovs_ej;
          return (
            <div key={f.id} className="rounded-lg border border-stone-200 bg-white p-3">
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-stone-800">{f.namn}</span>
                <Badge cls={STATUS[f.status].cls}>{STATUS[f.status].label}</Badge>
                <span className="text-xs text-stone-400">fas: {f.fas}</span>
                {golive > 0 && f.fas === "senare" && (
                  <Badge cls="bg-rose-100 text-rose-800">⚠ blockerar go-live men ligger i "senare"</Badge>
                )}
              </div>
              <div className="flex h-3 w-full overflow-hidden rounded-full bg-stone-100" role="img"
                   aria-label={`${golive} go-live, ${kan_vanta} kan vänta, ${behovs_ej} behövs ej`}>
                {golive > 0 && <div className="bg-rose-600" style={{ width: `${(golive / max) * 100}%` }} />}
                {kan_vanta > 0 && <div className="bg-amber-500" style={{ width: `${(kan_vanta / max) * 100}%` }} />}
                {behovs_ej > 0 && <div className="bg-stone-400" style={{ width: `${(behovs_ej / max) * 100}%` }} />}
              </div>
              <div className="mt-1 flex gap-4 text-xs text-stone-500">
                <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-rose-600" />{golive} go-live</span>
                <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-500" />{kan_vanta} kan vänta</span>
                <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-stone-400" />{behovs_ej} behövs ej</span>
                <span className="text-stone-300">({tot} svar)</span>
              </div>
              {workarounds.length > 0 && (
                <div className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-900">
                  <strong>Workaround-bank:</strong>
                  <ul className="ml-4 list-disc">
                    {workarounds.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [vy, setVy] = useState("trad");
  const [bedomningar, setBedomningar] = useState(START_BEDOMNINGAR);

  const flikar = [
    { id: "trad", label: "Kravträd" },
    { id: "bedomning", label: "Bedömning" },
    { id: "analys", label: "Analys" },
  ];

  return (
    <div className="min-h-screen bg-stone-50 font-sans text-stone-900">
      <header className="border-b-2 border-blue-900 bg-white px-4 py-3 sm:px-6">
        <h1 className="font-serif text-lg text-blue-900">Förmågekartan</h1>
        <p className="text-xs text-stone-500">Kravdatabas · prototyp · exempeldata</p>
      </header>

      <nav className="flex gap-1 border-b border-stone-200 bg-white px-4 sm:px-6" role="tablist">
        {flikar.map((f) => (
          <button
            key={f.id}
            role="tab"
            aria-selected={vy === f.id}
            onClick={() => setVy(f.id)}
            className={`border-b-2 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-700 ${
              vy === f.id
                ? "border-blue-900 font-medium text-blue-900"
                : "border-transparent text-stone-500 hover:text-stone-800"
            }`}
          >
            {f.label}
          </button>
        ))}
      </nav>

      <main className="mx-auto max-w-4xl px-4 py-5 sm:px-6">
        {vy === "trad" && <VyTrad />}
        {vy === "bedomning" && <VyBedomning bedomningar={bedomningar} setBedomningar={setBedomningar} />}
        {vy === "analys" && <VyAnalys bedomningar={bedomningar} />}
      </main>
    </div>
  );
}
