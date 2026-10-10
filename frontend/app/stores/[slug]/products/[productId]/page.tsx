import ProductDetail from "./product-detail";

export const instant = false;

export default async function StoreProductPage({ params }: { params: Promise<{ slug: string; productId: string }> }) {
  const { slug, productId } = await params;
  return <ProductDetail slug={slug} productId={productId} />;
}
