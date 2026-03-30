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
    setLoading(true);
    setError("");
    try {
      const params: Record<string, string> = { page: String(p), page_size: "20" };
      if (search) params.search = search;
      if (nutriscore) params.nutriscore = nutriscore;
      const result = await fetchProducts(params);
      setData(result);
      setPage(p);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;

  return (
    <div>
      <h2>GET /products</h2>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input
          placeholder="Search name/brand..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && doSearch(1)}
          style={{ padding: 6, flex: 1, minWidth: 200 }}
        />
        <select value={nutriscore} onChange={(e) => setNutriscore(e.target.value)} style={{ padding: 6 }}>
          <option value="">Any nutriscore</option>
          {["a", "b", "c", "d", "e"].map((g) => (
            <option key={g} value={g}>{g.toUpperCase()}</option>
          ))}
        </select>
        <button onClick={() => doSearch(1)} style={{ padding: "6px 16px" }}>
          Search
        </button>
      </div>

      {loading && <p>Loading...</p>}
      {error && <p style={{ color: "red" }}>{error}</p>}

      {data && (
        <>
          <p>{data.total} results (page {data.page} of {totalPages})</p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "2px solid #ccc" }}>
                <th style={{ padding: 4 }}>Name</th>
                <th style={{ padding: 4 }}>Brand</th>
                <th style={{ padding: 4 }}>Category</th>
                <th style={{ padding: 4 }}>Score</th>
                <th style={{ padding: 4 }}>kcal/100g</th>
                <th style={{ padding: 4 }}>Protein/100g</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((p) => (
                <tr
                  key={p.code}
                  onClick={() => onSelect(p.code)}
                  style={{ borderBottom: "1px solid #eee", cursor: "pointer" }}
                >
                  <td style={{ padding: 4 }}>{p.product_name}</td>
                  <td style={{ padding: 4 }}>{p.brands ?? "-"}</td>
                  <td style={{ padding: 4 }}>{p.category_label ?? "-"}</td>
                  <td style={{ padding: 4 }}>{p.nutriscore_grade?.toUpperCase() ?? "-"}</td>
                  <td style={{ padding: 4 }}>{p.energy_kcal_100g ?? "-"}</td>
                  <td style={{ padding: 4 }}>{p.proteins_100g ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button disabled={page <= 1} onClick={() => doSearch(page - 1)}>Prev</button>
            <button disabled={page >= totalPages} onClick={() => doSearch(page + 1)}>Next</button>
          </div>
        </>
      )}
    </div>
  );
}
