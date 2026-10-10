import Checkout from "./checkout-client";

export const instant = false;

export default async function CheckoutPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <Checkout slug={slug} />;
}
