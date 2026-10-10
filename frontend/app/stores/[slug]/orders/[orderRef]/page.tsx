import OrderConfirmation from "./order-confirmation";

export const instant = false;

export default async function OrderPage({ params }: { params: Promise<{ slug: string; orderRef: string }> }) {
  const { slug, orderRef } = await params;
  return <OrderConfirmation slug={slug} orderRef={orderRef} />;
}
