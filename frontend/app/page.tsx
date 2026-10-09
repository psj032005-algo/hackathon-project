
"use client";

import { useMemo, useState } from "react";

type Product = {
  id: number;
  name: string;
  category: string;
  price: number;
  originalPrice: number;
  stock: number;
  image: string;
  description: string;
};

const PRODUCTS: Product[] = [
  {
    id: 1,
    name: "Everyday Tote Bag",
    category: "Accessories",
    price: 799,
    originalPrice: 999,
    stock: 18,
    image: "https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=700&q=85",
    description: "A versatile everyday bag with a clean, minimal look.",
  },
  {
    id: 2,
    name: "Classic Ceramic Mug",
    category: "Home",
    price: 399,
    originalPrice: 499,
    stock: 25,
    image: "https://images.unsplash.com/photo-1514228742587-6b1558fcca3d?auto=format&fit=crop&w=700&q=85",
    description: "A simple ceramic mug for your favourite daily drink.",
  },
  {
    id: 3,
    name: "Minimal Wrist Watch",
    category: "Accessories",
    price: 1499,
    originalPrice: 1899,
    stock: 7,
    image: "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=700&q=85",
    description: "A timeless watch with an understated modern design.",
  },
  {
    id: 4,
    name: "Daily Skincare Set",
    category: "Beauty",
    price: 999,
    originalPrice: 999,
    stock: 12,
    image: "https://images.unsplash.com/photo-1608248543803-ba4f8c70ae0b?auto=format&fit=crop&w=700&q=85",
    description: "A simple self-care set for your everyday routine.",
  },
  {
    id: 5,
    name: "Classic Sneakers",
    category: "Fashion",
    price: 1799,
    originalPrice: 2299,
    stock: 0,
    image: "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=700&q=85",
    description: "Comfortable everyday sneakers with a bold silhouette.",
  },
  {
    id: 6,
    name: "Desk Plant Pot",
    category: "Home",
    price: 549,
    originalPrice: 699,
    stock: 9,
    image: "https://images.unsplash.com/photo-1485955900006-10f4d324d411?auto=format&fit=crop&w=700&q=85",
    description: "Bring a little greenery to your desk or living space.",
  },
];

const CATEGORIES = ["All", ...Array.from(new Set(PRODUCTS.map((p) => p.category)))];

const money = (amount: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);

export default function Home() {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [cart, setCart] = useState<Record<number, number>>({});
  const [cartOpen, setCartOpen] = useState(false);
  const [notice, setNotice] = useState("");

  const filteredProducts = useMemo(() => {
    const term = search.trim().toLowerCase();

    return PRODUCTS.filter((product) => {
      const matchesCategory = category === "All" || product.category === category;
      const matchesSearch =
        !term ||
        product.name.toLowerCase().includes(term) ||
        product.category.toLowerCase().includes(term) ||
        product.description.toLowerCase().includes(term);

      return matchesCategory && matchesSearch;
    });
  }, [search, category]);

  const cartItems = PRODUCTS.filter((product) => (cart[product.id] || 0) > 0);
  const cartCount = Object.values(cart).reduce((sum, qty) => sum + qty, 0);
  const cartTotal = cartItems.reduce(
    (sum, product) => sum + product.price * cart[product.id],
    0,
  );

  function addToCart(product: Product) {
    if (product.stock <= (cart[product.id] || 0)) {
      setNotice(`Sorry, no more stock available for ${product.name}.`);
      return;
    }

    setCart((previous) => ({
      ...previous,
      [product.id]: (previous[product.id] || 0) + 1,
    }));
    setNotice(`${product.name} added to your cart.`);
  }

  function changeQuantity(product: Product, delta: number) {
    setCart((previous) => {
      const nextQuantity = (previous[product.id] || 0) + delta;
      const next = { ...previous };

      if (nextQuantity <= 0) {
        delete next[product.id];
      } else if (nextQuantity <= product.stock) {
        next[product.id] = nextQuantity;
      }

      return next;
    });
  }

  return (
    <main className="min-h-screen bg-[#faf9f6] text-[#22251f]">
      <div className="bg-[#243c30] px-4 py-2.5 text-center text-xs font-medium tracking-wide text-white sm:text-sm">
        A LITTLE SOMETHING SPECIAL · DISCOVER YOUR NEW FAVOURITES
      </div>

      <header className="sticky top-0 z-20 border-b border-black/5 bg-[#faf9f6]/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <a href="#" className="text-2xl font-semibold tracking-tight sm:text-3xl">
            little<span className="text-[#9b7753]">market.</span>
          </a>

          <nav className="hidden items-center gap-7 text-sm text-gray-600 md:flex">
            <a href="#catalogue" className="hover:text-[#243c30]">Shop all</a>
            <a href="#catalogue" onClick={() => setCategory("Home")} className="hover:text-[#243c30]">Home</a>
            <a href="#catalogue" onClick={() => setCategory("Accessories")} className="hover:text-[#243c30]">Accessories</a>
            <a href="#about" className="hover:text-[#243c30]">Our story</a>
          </nav>

          <button
            onClick={() => setCartOpen(!cartOpen)}
            className="rounded-full border border-[#d9d8cf] px-4 py-2 text-sm font-semibold transition hover:bg-white"
            aria-label="Open shopping cart"
          >
            Bag ({cartCount})
          </button>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl gap-8 px-5 py-10 sm:px-8 sm:py-14 lg:grid-cols-2 lg:items-center lg:gap-14 lg:py-20">
        <div className="py-4 sm:py-8">
          <p className="mb-5 text-xs font-semibold uppercase tracking-[0.25em] text-[#9b7753]">
            GOOD THINGS, CHOSEN WITH CARE
          </p>
          <h1 className="max-w-xl text-5xl font-medium leading-[1.08] tracking-tight sm:text-6xl lg:text-7xl">
            Find joy in the <span className="font-serif italic text-[#607c62]">little</span> things.
          </h1>
          <p className="mt-6 max-w-md text-base leading-7 text-gray-600 sm:text-lg">
            Thoughtful everyday essentials for your home, your style, and all the moments in between.
          </p>
          <a
            href="#catalogue"
            className="mt-8 inline-flex items-center gap-3 rounded-full bg-[#243c30] px-7 py-3.5 text-sm font-semibold text-white transition hover:bg-[#355642]"
          >
            Explore the collection <span aria-hidden="true">↗</span>
          </a>
          <div className="mt-10 flex gap-8 border-t border-[#e6e2d9] pt-6 text-sm">
            <div><strong className="block text-xl">6</strong><span className="text-gray-500">Curated finds</span></div>
            <div><strong className="block text-xl">4</strong><span className="text-gray-500">Categories</span></div>
            <div><strong className="block text-xl">100%</strong><span className="text-gray-500">Good vibes</span></div>
          </div>
        </div>

        <div className="relative">
          <img
            src="https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=1200&q=90"
            alt="Beautifully arranged modern lifestyle store"
            className="h-[340px] w-full rounded-[2rem] object-cover sm:h-[470px] lg:h-[540px]"
          />
          <div className="absolute bottom-5 left-5 rounded-2xl bg-[#faf9f6] px-5 py-4 shadow-lg sm:bottom-7 sm:left-7">
            <p className="text-xs uppercase tracking-widest text-gray-500">The everyday edit</p>
            <p className="mt-1 font-serif text-xl italic">Simple. Useful. Lovely.</p>
          </div>
        </div>
      </section>

      <section id="catalogue" className="mx-auto max-w-7xl scroll-mt-24 px-5 py-12 sm:px-8 sm:py-16">
        <div className="flex flex-col gap-6 border-b border-[#e6e2d9] pb-7 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#9b7753]">THE COLLECTION</p>
            <h2 className="mt-2 text-3xl font-medium tracking-tight sm:text-4xl">Things you’ll love.</h2>
            <p className="mt-2 text-sm text-gray-500">{filteredProducts.length} products to explore</p>
          </div>

          <label className="flex w-full items-center gap-3 rounded-full border border-[#dedbd2] bg-white px-4 py-3 sm:max-w-xs">
            <span aria-hidden="true">⌕</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Find something lovely..."
              className="w-full bg-transparent text-sm outline-none placeholder:text-gray-400"
              aria-label="Search products"
            />
            {search && (
              <button onClick={() => setSearch("")} className="text-gray-500" aria-label="Clear search">×</button>
            )}
          </label>
        </div>

        <div className="my-7 flex gap-2 overflow-x-auto pb-2">
          {CATEGORIES.map((item) => (
            <button
              key={item}
              onClick={() => setCategory(item)}
              className={`shrink-0 rounded-full px-5 py-2.5 text-sm transition ${
                category === item
                  ? "bg-[#243c30] text-white"
                  : "border border-[#dedbd2] bg-white text-gray-600 hover:border-[#243c30]"
              }`}
            >
              {item}
            </button>
          ))}
        </div>

        {filteredProducts.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-[#d8d3c9] py-20 text-center">
            <p className="text-lg font-medium">No products found</p>
            <p className="mt-2 text-sm text-gray-500">Try another search or category.</p>
            <button
              onClick={() => { setSearch(""); setCategory("All"); }}
              className="mt-5 underline underline-offset-4"
            >
              Clear filters
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-x-6 gap-y-10 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3">
            {filteredProducts.map((product) => {
              const discount = product.originalPrice > product.price
                ? Math.round((1 - product.price / product.originalPrice) * 100)
                : 0;
              const quantityInCart = cart[product.id] || 0;

              return (
                <article key={product.id} className="group">
                  <div className="relative overflow-hidden rounded-2xl bg-[#efede6]">
                    <img
                      src={product.image}
                      alt={product.name}
                      loading="lazy"
                      className="h-[310px] w-full object-cover transition duration-500 group-hover:scale-[1.04] sm:h-[360px]"
                    />
                    {discount > 0 && (
                      <span className="absolute left-4 top-4 rounded-full bg-white px-3 py-1.5 text-xs font-semibold">
                        {discount}% off
                      </span>
                    )}
                    {product.stock === 0 && (
                      <span className="absolute inset-x-0 bottom-0 bg-black/65 py-2.5 text-center text-xs font-semibold uppercase tracking-wider text-white">
                        Out of stock
                      </span>
                    )}
                  </div>

                  <div className="flex items-start justify-between gap-3 pt-4">
                    <div>
                      <p className="text-xs uppercase tracking-widest text-[#9b7753]">{product.category}</p>
                      <h3 className="mt-1 text-lg font-medium">{product.name}</h3>
                      <p className="mt-1 max-w-xs text-sm leading-5 text-gray-500">{product.description}</p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="font-semibold">{money(product.price)}</p>
                      {discount > 0 && (
                        <p className="text-sm text-gray-400 line-through">{money(product.originalPrice)}</p>
                      )}
                    </div>
                  </div>

                  <button
                    onClick={() => addToCart(product)}
                    disabled={product.stock === 0 || quantityInCart >= product.stock}
                    className="mt-4 w-full rounded-full border border-[#243c30] px-5 py-3 text-sm font-semibold transition hover:bg-[#243c30] hover:text-white disabled:cursor-not-allowed disabled:border-gray-300 disabled:text-gray-400 disabled:hover:bg-transparent disabled:hover:text-gray-400"
                  >
                    {product.stock === 0 ? "Unavailable" : quantityInCart > 0 ? `Add another · ${quantityInCart} in bag` : "Add to bag +"}
                  </button>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section id="about" className="bg-[#e9e9df] px-5 py-16 sm:px-8 sm:py-20">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#9b7753]">A LITTLE ABOUT US</p>
          <h2 className="mt-3 font-serif text-3xl italic sm:text-4xl">Everyday things, made to feel special.</h2>
          <p className="mx-auto mt-5 max-w-2xl text-sm leading-7 text-gray-600 sm:text-base">
            We believe the things we use every day deserve a little thought. This demo shop brings together useful, beautiful finds for a home and life you love.
          </p>
        </div>
      </section>

      <footer className="bg-[#243c30] px-5 py-10 text-white sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-2xl font-semibold">little<span className="text-[#c5a783]">market.</span></p>
          <p className="text-sm text-white/70">Thoughtful finds for everyday living.</p>
          <p className="text-xs text-white/60">© 2026 littlemarket. Demo storefront.</p>
        </div>
      </footer>

      {notice && (
        <div role="status" className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-full bg-[#243c30] px-5 py-3 text-center text-sm text-white shadow-xl">
          {notice}
          <button onClick={() => setNotice("")} className="ml-3 font-bold" aria-label="Dismiss notification">×</button>
        </div>
      )}

      {cartOpen && (
        <div className="fixed inset-0 z-40">
          <button
            aria-label="Close cart"
            className="absolute inset-0 h-full w-full bg-black/40"
            onClick={() => setCartOpen(false)}
          />
          <aside className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col bg-[#faf9f6] p-6 shadow-2xl sm:p-8">
            <div className="flex items-center justify-between border-b border-[#e6e2d9] pb-5">
              <div>
                <h2 className="text-2xl font-medium">Your bag</h2>
                <p className="mt-1 text-sm text-gray-500">{cartCount} items</p>
              </div>
              <button onClick={() => setCartOpen(false)} className="rounded-full border px-3 py-1.5" aria-label="Close cart">×</button>
            </div>

            <div className="flex-1 overflow-y-auto">
              {cartItems.length === 0 ? (
                <div className="py-16 text-center">
                  <p className="text-lg font-medium">Your bag is waiting.</p>
                  <p className="mt-2 text-sm text-gray-500">Add something you love to get started.</p>
                </div>
              ) : (
                <div className="divide-y divide-[#e6e2d9]">
                  {cartItems.map((product) => (
                    <div key={product.id} className="flex gap-4 py-5">
                      <img src={product.image} alt="" className="h-24 w-20 rounded-xl object-cover" />
                      <div className="flex flex-1 flex-col">
                        <p className="font-medium">{product.name}</p>
                        <p className="mt-1 text-sm text-gray-500">{money(product.price)}</p>
                        <div className="mt-auto flex items-center gap-3">
                          <button onClick={() => changeQuantity(product, -1)} className="rounded-full border px-2.5 py-1" aria-label={`Remove one ${product.name}`}>−</button>
                          <span className="text-sm">{cart[product.id]}</span>
                          <button onClick={() => changeQuantity(product, 1)} disabled={cart[product.id] >= product.stock} className="rounded-full border px-2.5 py-1 disabled:opacity-40" aria-label={`Add one ${product.name}`}>+</button>
                          <button onClick={() => setCart((previous) => { const next = { ...previous }; delete next[product.id]; return next; })} className="ml-auto text-xs text-gray-500 underline">Remove</button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="border-t border-[#e6e2d9] pt-5">
              <div className="flex justify-between text-base font-semibold">
                <span>Subtotal</span><span>{money(cartTotal)}</span>
              </div>
              <p className="mt-2 text-xs text-gray-500">Shipping and taxes are calculated at checkout.</p>
              <button
                onClick={() => setNotice("Checkout will be connected when the backend order API is ready.")}
                disabled={cartItems.length === 0}
                className="mt-5 w-full rounded-full bg-[#243c30] px-5 py-3.5 text-sm font-semibold text-white hover:bg-[#355642] disabled:cursor-not-allowed disabled:opacity-40"
              >
                Continue to checkout
              </button>
              <button onClick={() => setCartOpen(false)} className="mt-3 w-full py-2 text-sm text-gray-600 underline underline-offset-4">Continue shopping</button>
            </div>
          </aside>
        </div>
      )}
    </main>
  );
}
