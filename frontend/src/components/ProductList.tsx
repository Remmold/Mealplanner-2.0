import { useState } from "react";
import { fetchProducts, type PaginatedProducts } from "../api";

export default function ProductList({ onSelect }: { onSelect: (code: string) => void }) {
  const [search, setSearch] = useState("");
  const [nutriscore, setNutriscore] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PaginatedProducts | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function doSearch(p = page) {
    setLoading(true); setError("");
    try {
      const params: Record<string, string> = { page: String(p), page_size: "20" };
      if (search) params.search = search;
      if (nutriscore) params.nutriscore = nutriscore;
      const result = await fetchProducts(params);
      setData(result); setPage(p);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;

  function scoreColor(grade: string | null | undefined) {
    if (!grade) return { background: "var(--cream-2)", color: "var(--taupe-2)" };
    const colors: Record<string, { background: string; color: string }> = {
      a: { background: "#a8d5a8", color: "#1d4d1d" },
      b: { background: "#cce5b8", color: "#3d5f1d" },
      c: { background: "var(--honey-soft)", color: "var(--terracotta-dark)" },
      d: { background: "#f0c7a3", color: "#8a4a1a" },
      e: { background: "#f0a89a", color: "#7a2a1a" },
    };
    return colors[grade.toLowerCase()] ?? colors.c;
  }

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>Browse products</h1>
        <p>Search ~50,000 packaged products from Open Food Facts. Filter by nutriscore, click a product for full nutrition.</p>
      </div>

      <div className="card">
        <div className="row gap-2 wrap">
          <input
            className="input flex-1"
            placeholder="Search name or brand..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doSearch(1)}
          />
          <select className="select" value={nutriscore} onChange={(e) => setNutriscore(e.target.value)} style={{ width: "auto" }}>
            <option value="">Any nutriscore</option>
            {["a", "b", "c", "d", "e"].map((g) => <option key={g} value={g}>{g.toUpperCase()}</option>)}
          </select>
          <button onClick={() => doSearch(1)} className="btn btn-primary">Search</button>
        </div>

        {error && <div className="error mt-3">{error}</div>}
        {loading && <p className="muted mt-3">Loading...</p>}

        {data && (
          <>
            <p className="small muted mt-3">{data.total.toLocaleString()} results · page {data.page} of {totalPages}</p>
            <div className="list mt-2">
              {data.items.map((p) => {
                const sc = scoreColor(p.nutriscore_grade);
                return (
                  <div key={p.code} onClick={() => onSelect(p.code)} className="list-row" style={{ cursor: "pointer" }}>
                    <div className="flex-1">
                      <div style={{ fontWeight: 500 }}>{p.product_name}</div>
                      <div className="tiny muted">{p.brands ?? "—"} · {p.category_label ?? "Uncategorized"}</div>
                    </div>
                    <span className="pill" style={{ background: sc.background, color: sc.color, borderColor: "transparent", fontWeight: 600 }}>
                      {p.nutriscore_grade?.toUpperCase() ?? "?"}
                    </span>
                    <div className="right" style={{ width: 90 }}>
                      <div style={{ fontWeight: 500 }}>{p.energy_kcal_100g ?? "—"}</div>
                      <div className="tiny muted">kcal/100g</div>
                    </div>
                    <div className="right" style={{ width: 80 }}>
                      <div style={{ fontWeight: 500 }}>{p.proteins_100g ?? "—"}</div>
                      <div className="tiny muted">protein</div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="row gap-2 mt-4">
              <button disabled={page <= 1} onClick={() => doSearch(page - 1)} className="btn">← Prev</button>
              <button disabled={page >= totalPages} onClick={() => doSearch(page + 1)} className="btn">Next →</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
