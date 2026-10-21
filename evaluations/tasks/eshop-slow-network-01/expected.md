# Expected finding

On a slow network, a second click on "Place order" while the first is still in flight places the same order twice. A single click places one order on any network.

- Customers sign in with the seeded users `alice` or `bob`, password `Pass123$`, from `src/Identity.API/UsersSeed.cs`.
- With about 2000 ms of added latency, a second click 0.5 to 1.5 seconds after the first sends a second `POST /checkout`. The browser aborts the first request (`net::ERR_ABORTED`), but the server has already taken it, and both create an order.
- The customer's Orders page (`/user/orders`) then shows two orders with the same lines and total, created less than a second apart. In `orderingdb`, `ordering.orders` has both, with the same buyer and the same `ordering."orderItems"`.
- Without throttling, the first submit is answered in well under a second and the page moves on to Orders, so a second click does not submit again.

Reproduction, from https://localhost:7298 with the AppHost running:

1. Sign in as `alice`.
2. Add a product, such as Adventurer GPS Watch, to the shopping bag, and go to Checkout.
3. Throttle the browser's network, for example with Chrome DevTools or CDP `Network.emulateNetworkConditions` at 2000 ms latency, or `tc qdisc ... netem delay`.
4. Click "Place order", then click it again about 0.7 seconds later.
5. Open Orders: two new orders with the same lines.

A correct result shows the second order in the order history or on the server side, not only that the button stays enabled.

Cause: `patches/order-summary.patch` adds an Order summary to `src/WebApp/Components/Pages/Checkout/Checkout.razor`, whose lines are posted back as hidden fields. `BasketState.CheckoutAsync` in `src/WebApp/Services/BasketState.cs` builds the order from those posted lines, priced from the catalog, instead of from the basket, and `PerformCustomValidation` in `Checkout.razor` checks the posted lines for "Your cart is empty" instead of the basket. Upstream, a repeat submit that reaches the server after the first order has emptied the basket fails that check. With the patch it passes, and nothing else stops it: the order's `RequestId` is not posted with the form, so each submit gets a new one.

## Setup

The project is eShop at upstream commit `913acea6` with the patch applied, as a repository of one commit. Nothing was installed or built: the machine needs the .NET 10 SDK (`global.json`), and Ubuntu's `libicu74` for .NET to start. `dotnet run --project src/eShop.AppHost` builds everything, fetches the Aspire CLI, and starts Postgres, Redis, and RabbitMQ on the machine's Docker. The store is at https://localhost:7298 and sign-in at https://localhost:5243. The Postgres container outlives the AppHost, so the orders in the task's materials are those in the database after the check, however the agent stopped the shop.

## Not defects

These are upstream eShop behavior, or setup of the machine:

- .NET does not start until libicu is installed.
- There is no sign-up page. Customers are the seeded users `alice` and `bob`.
- The https development certificate is not trusted on Linux; Aspire prints that developer certificates may not be fully trusted.
- "Place order" is never disabled while an order is submitted, in upstream too. Only the duplicate order is the defect.
- Two submits less than about 50 ms apart place two orders in upstream too, since both pass the basket check before the first empties the basket.
- A new order stays Submitted for about a minute, the OrderProcessor's grace period, before it moves through its other statuses.
- On a slow or interrupted link, the Orders page may not refresh a status change by itself; its live updates run over the Blazor Server circuit.
- The chatbot button opens a chat with no AI behind it, since no chat model is configured.
- Catalog search falls back to a search by name, since no embedding model is configured.
- Pages with stream rendering, such as the catalog, the shopping bag, and Orders, show a loading state first on a slow link.
- The Aspire CLI prints a notice that an update is available.
