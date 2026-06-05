import katex from "katex";
import "katex/dist/katex.min.css";
import { useMDStore } from "./store";
import type { ForceTerm } from "./types";

// Render a LaTeX string with KaTeX. throwOnError:false → malformed TeX shows in
// red rather than crashing the panel.
function TeX({ tex, block = false }: { tex: string; block?: boolean }) {
  const html = katex.renderToString(tex, { throwOnError: false, displayMode: block });
  return <span className="katex-host" dangerouslySetInnerHTML={{ __html: html }} />;
}

function num(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return Number.isInteger(x) ? String(x) : x.toFixed(3).replace(/\.?0+$/, "");
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-border rounded-lg p-3 bg-canvas/40 space-y-2">
      <div className="text-[11px] font-semibold text-indigo-300 uppercase tracking-wider">{title}</div>
      {children}
    </div>
  );
}

function Eq({ children }: { children: React.ReactNode }) {
  return <div className="overflow-x-auto py-0.5 text-slate-100">{children}</div>;
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] text-slate-500 leading-snug">{children}</p>;
}

// Each renderer below mirrors the exact maths in backend/app/md/forces.py,
// integrators.py and engine.py — including the parts that differ from the
// textbook (shifted-force LJ, numerical derivative for formulas, the
// semi-implicit Euler "leapfrog", the simple velocity-rescale).
function ForceMath({ term }: { term: ForceTerm }) {
  if (term.kind === "lennard_jones") {
    const rc = term.cutoff;
    return (
      <Block title="Lennard-Jones (12-6)">
        <Eq><TeX block tex={String.raw`U(r)=4\varepsilon\left[\left(\tfrac{\sigma}{r}\right)^{12}-\left(\tfrac{\sigma}{r}\right)^{6}\right]`} /></Eq>
        <Eq><TeX block tex={String.raw`F(r)=-\frac{dU}{dr}=\frac{24\varepsilon}{r}\left[2\left(\tfrac{\sigma}{r}\right)^{12}-\left(\tfrac{\sigma}{r}\right)^{6}\right]`} /></Eq>
        {rc != null && (
          <>
            <Note>With a cutoff this code uses the <b>shifted-force</b> form (so U and F reach 0 smoothly at <TeX tex={String.raw`r_c=${num(rc)}\,\sigma`} /> — this is what keeps NVE energy conserved):</Note>
            <Eq><TeX block tex={String.raw`U_{\mathrm{sf}}(r)=U(r)-U(r_c)+F(r_c)\,(r-r_c),\quad F_{\mathrm{sf}}(r)=F(r)-F(r_c)\quad (r<r_c)`} /></Eq>
          </>
        )}
        <Eq><TeX tex={String.raw`\mathbf{F}_i=\sum_{j}\frac{F(r_{ij})}{r_{ij}}\,(\mathbf{r}_i-\mathbf{r}_j)`} /></Eq>
        <Note>Now: <TeX tex={String.raw`\varepsilon=${num(term.epsilon)},\ \sigma=${num(term.sigma)}${rc != null ? String.raw`,\ r_c=${num(rc)}\sigma` : ""}`} />.</Note>
      </Block>
    );
  }
  if (term.kind === "coulomb") {
    return (
      <Block title="Coulomb">
        <Eq><TeX block tex={String.raw`U(r)=k\,\frac{q_i q_j}{r},\qquad \mathbf{F}_i=k\,\frac{q_i q_j}{r^{3}}\,(\mathbf{r}_i-\mathbf{r}_j)`} /></Eq>
        <Note>Charges <TeX tex={String.raw`q`} /> are per particle type; <TeX tex={String.raw`k=${num(term.k_coulomb)}`} /> (reduced units). {term.coulomb_cutoff != null ? <>Hard cutoff at <TeX tex={String.raw`r_c=${num(term.coulomb_cutoff)}`} /> (no shifting).</> : "No cutoff."}</Note>
      </Block>
    );
  }
  if (term.kind === "gravity") {
    return (
      <Block title="Gravity (softened)">
        <Eq><TeX block tex={String.raw`U(r)=-\frac{G\,m_i m_j}{\sqrt{r^{2}+\epsilon_s^{2}}}`} /></Eq>
        <Eq><TeX block tex={String.raw`\mathbf{F}_i=-\frac{G\,m_i m_j}{\left(r^{2}+\epsilon_s^{2}\right)^{3/2}}\,(\mathbf{r}_i-\mathbf{r}_j)`} /></Eq>
        <Note>Softening <TeX tex={String.raw`\epsilon_s=${num(term.softening)}`} /> removes the singularity at <TeX tex={String.raw`r\to0`} />; <TeX tex={String.raw`G=${num(term.g_constant)}`} />. Attractive (toward <TeX tex={String.raw`j`} />).</Note>
      </Block>
    );
  }
  if (term.kind === "harmonic_bond") {
    return (
      <Block title="Harmonic bond">
        <Eq><TeX block tex={String.raw`U(r)=\tfrac{1}{2}k\,(r-r_0)^{2},\qquad \mathbf{F}_i=-k\,(r-r_0)\,\hat{\mathbf{r}}`} /></Eq>
        <Note><TeX tex={String.raw`\hat{\mathbf{r}}=(\mathbf{r}_i-\mathbf{r}_j)/r`} />. Each bond has its own <TeX tex={String.raw`r_0,k`} /> (from the bond list). Bonds use the raw displacement — they ignore periodic images.</Note>
      </Block>
    );
  }
  if (term.kind === "formula") {
    return (
      <Block title="Custom formula U(r)">
        <Eq><TeX block tex={String.raw`U(r)=${term.expression ? texEscape(term.expression) : "\\text{(your expression)}"}`} /></Eq>
        <Eq><TeX block tex={String.raw`F(r)=-\frac{dU}{dr}\approx-\frac{U(r+h)-U(r-h)}{2h},\quad h=10^{-5}`} /></Eq>
        <Note>The force is a <b>central finite-difference</b> derivative of your potential (the engine evaluates it numerically; an exact symbolic derivative is used only if SymPy is available).</Note>
      </Block>
    );
  }
  if (term.kind === "python") {
    return (
      <Block title="Custom Python force">
        <Note>The force is whatever your <TeX tex={String.raw`\texttt{force(pos, type\_index, box, params)}`} /> returns — no closed form. It must return <TeX tex={String.raw`(\mathbf{F},\,U)`} /> with <TeX tex={String.raw`\mathbf{F}\in\mathbb{R}^{N\times3}`} />.</Note>
      </Block>
    );
  }
  return null;
}

// Minimal sanitiser so a user's Python-ish expression renders as TeX without
// crashing (it is shown verbatim, not claimed to be typeset perfectly).
function texEscape(expr: string): string {
  return expr
    .replace(/\*\*/g, "^")
    .replace(/\*/g, String.raw`\cdot `)
    .replace(/_/g, String.raw`\_`);
}

export function MathPanel() {
  const spec = useMDStore((s) => s.spec);
  const enabled = spec.force_terms.filter((t) => t.enabled);

  return (
    <div className="space-y-3 text-sm">
      <Note>
        Every equation below is exactly what the engine computes for this setup (reduced units, <TeX tex={String.raw`k_B=1`} />). Distances use the minimum-image convention under periodic boundaries.
      </Note>

      {enabled.length === 0 && <Note>No force terms enabled.</Note>}
      {enabled.map((t, i) => <ForceMath key={i} term={t} />)}

      <Block title={spec.integrator === "leapfrog" ? "Integration — semi-implicit Euler" : "Integration — velocity Verlet"}>
        {spec.integrator === "leapfrog" ? (
          <>
            <Eq><TeX block tex={String.raw`\mathbf{v}_{t+\Delta t}=\mathbf{v}_t+\mathbf{a}_t\,\Delta t,\qquad \mathbf{r}_{t+\Delta t}=\mathbf{r}_t+\mathbf{v}_{t+\Delta t}\,\Delta t`} /></Eq>
            <Note>This is the semi-implicit (Euler–Cromer) update — velocity is advanced first, then position uses the new velocity. <TeX tex={String.raw`\mathbf{a}=\mathbf{F}/m`} />, <TeX tex={String.raw`\Delta t=${num(spec.dt)}`} />.</Note>
          </>
        ) : (
          <>
            <Eq><TeX block tex={String.raw`\mathbf{r}_{t+\Delta t}=\mathbf{r}_t+\mathbf{v}_t\,\Delta t+\tfrac{1}{2}\mathbf{a}_t\,\Delta t^{2}`} /></Eq>
            <Eq><TeX block tex={String.raw`\mathbf{v}_{t+\Delta t}=\mathbf{v}_t+\tfrac{1}{2}\left(\mathbf{a}_t+\mathbf{a}_{t+\Delta t}\right)\Delta t`} /></Eq>
            <Note>Symplectic; conserves energy over long runs. <TeX tex={String.raw`\mathbf{a}=\mathbf{F}/m`} />, <TeX tex={String.raw`\Delta t=${num(spec.dt)}`} />.</Note>
          </>
        )}
      </Block>

      <Block title="Temperature & velocity init">
        <Eq><TeX block tex={String.raw`T=\frac{2E_k}{(3N-3)\,k_B},\qquad E_k=\tfrac{1}{2}\sum_i m_i\lVert\mathbf{v}_i\rVert^{2}`} /></Eq>
        <Note>Degrees of freedom are <TeX tex={String.raw`3N-3`} /> (centre-of-mass drift removed). Initial velocities are Maxwell–Boltzmann: <TeX tex={String.raw`v_{i\alpha}\sim\mathcal{N}(0,\,k_BT/m_i)`} />, COM velocity subtracted, then rescaled to hit <TeX tex={String.raw`T`} /> exactly.</Note>
      </Block>

      {spec.thermostat !== "none" && (
        <Block title={`Thermostat — ${spec.thermostat === "berendsen" ? "Berendsen" : "velocity rescale"}`}>
          {spec.thermostat === "berendsen" ? (
            <>
              <Eq><TeX block tex={String.raw`\lambda=\sqrt{1+\frac{\Delta t}{\tau}\left(\frac{T_0}{T}-1\right)},\qquad \mathbf{v}\leftarrow\lambda\mathbf{v}`} /></Eq>
              <Note><TeX tex={String.raw`T_0=${num(spec.target_temperature)}`} /> (target), <TeX tex={String.raw`\tau=${num(spec.thermostat_coupling)}`} /> (coupling).</Note>
            </>
          ) : (
            <>
              <Eq><TeX block tex={String.raw`\lambda=1+c\left(\sqrt{\tfrac{T_0}{T}}-1\right),\qquad \mathbf{v}\leftarrow\lambda\mathbf{v}`} /></Eq>
              <Note>A simple partial rescale toward <TeX tex={String.raw`T_0=${num(spec.target_temperature)}`} /> by fraction <TeX tex={String.raw`c=${num(spec.thermostat_coupling)}`} /> each step — not the stochastic Bussi (CSVR) thermostat.</Note>
            </>
          )}
        </Block>
      )}

      {spec.minimize_steps > 0 && (
        <Block title="Energy minimisation (preprocessing)">
          <Eq><TeX block tex={String.raw`\mathbf{r}\leftarrow\mathbf{r}+\alpha\,\mathbf{F}\quad(\text{steepest descent, } \lVert\Delta\mathbf{r}_i\rVert\le d_{\max})`} /></Eq>
          <Note>Accept the step only if <TeX tex={String.raw`U`} /> decreases; on accept grow <TeX tex={String.raw`\alpha\!\leftarrow\!1.1\alpha`} />, else revert and <TeX tex={String.raw`\alpha\!\leftarrow\!\alpha/2`} />. So <TeX tex={String.raw`U`} /> is monotonically non-increasing — removes clashes before dynamics. {spec.minimize_steps} steps.</Note>
        </Block>
      )}
    </div>
  );
}
