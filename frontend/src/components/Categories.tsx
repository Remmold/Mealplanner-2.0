import { useEffect, useState } from "react";
import { fetchCategories } from "../api";

export default function Categories() {
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    fetchCategories()
      .then(setCategories)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const filtered = filter
    ? categories.filter((c) => c.toLowerCase().includes(filter.toLowerCase()))
    : categories;

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>Product categories</h1>
        <p>The full list of cleaned product categories from the OFF dataset, used to organise the product browser.</p>
      </div>

      <div className="card">
        <div className="row between mb-3">
          <h3 style={{ margin: 0 }}>{filtered.length} of {categories.length}</h3>
          <input
            className="input"
            placeholder="Filter..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ width: 240 }}
          />
        </div>

        {loading && <p className="muted">Loading...</p>}
        {error && <div className="error">{error}</div>}

        {!loading && !error && (
          <div style={{ columns: 3, columnGap: "var(--space-4)" }}>
            {filtered.map((c) => (
              <div key={c} style={{ breakInside: "avoid", padding: "4px 0", fontSize: 14 }}>
                · {c}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
