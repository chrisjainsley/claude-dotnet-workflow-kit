---
title: Order status endpoint
ticket: AB#90001
branch: feat/AB#90001/order-status-endpoint
base: dev
size: standard
date: 2026-09-12
---

## Context
**Parent feature:** Order Tracking self-serve, so a buyer can check a shipment without
contacting support.

**Siblings:** none open.

**Area:** OrdersService, `Features/OrderStatus` feature folder. Reads the existing
`Order` and `Shipment` tables through Dapper.

**Designs:** none. Backend-only endpoint.

## Requirement
A signed-in buyer can fetch the current status of one of their own orders by order id.
The endpoint returns the order state, the carrier tracking number when shipped, and the
estimated delivery date when known.

Example: order `ORD-4821` placed Monday, shipped Wednesday, returns
`{"status":"Shipped","trackingNumber":"1Z999","eta":"2026-09-16"}`.

## Specs

```gherkin
Feature: Order status endpoint

  Scenario: A buyer checks a shipped order
    Given a buyer with a shipped order
    When the buyer requests the order status
    Then the response shows status "Shipped" and a tracking number

  Scenario: A buyer cannot check another buyer's order
    Given an order that belongs to a different buyer
    When the buyer requests that order's status
    Then the response is 403 Forbidden
```

## Slice
`Features/OrderStatus/GetOrderStatusEndpoint.cs` maps `GET /orders/{orderId}/status` to
`GetOrderStatusHandler`, which loads the order, checks ownership, and maps to
`OrderStatusResponse`.

```csharp
public record OrderStatusResponse(string Status, string? TrackingNumber, DateOnly? Eta);

public sealed class GetOrderStatusHandler(IOrderStatusReader reader)
{
    public async Task<OrderStatusResponse?> HandleAsync(Guid orderId, Guid buyerId, CancellationToken ct)
    {
        var order = await reader.GetAsync(orderId, ct);
        if (order is null || order.BuyerId != buyerId)
            return null;
        return new OrderStatusResponse(order.Status, order.TrackingNumber, order.Eta);
    }
}
```

## Persistence
`IOrderStatusReader.GetAsync` runs one Dapper query joining `Order` and `Shipment` on
`OrderId`, returning `TrackingNumber` and `Eta` as null until a shipment row exists. No
new table, no migration.

## Integration
No outbound call. The carrier tracking number is read from the existing `Shipment`
row; live carrier lookups stay out of scope for this endpoint.

## Endpoint
`GET /orders/{orderId}/status` returns 200 with `OrderStatusResponse`, 403 when the
order belongs to another buyer, 404 when the order id does not exist.

## Tests
| Project | Class | Cases |
|---|---|---|
| OrdersService.Tests | GetOrderStatusHandlerTests | GivenShippedOrder_ThenReturnsTrackingNumber, GivenOtherBuyersOrder_ThenReturnsNull, GivenUnknownOrder_ThenReturnsNull |
| OrdersService.API.Tests | GetOrderStatusEndpointTests | GivenOwnShippedOrder_ThenOk, GivenOtherBuyersOrder_ThenForbidden, GivenUnknownOrder_ThenNotFound |

## Decisions
- One Dapper query over a repository abstraction; the slice has no other read path to
  share.
- Ownership check inside the handler, not a filter, so the 403 path is covered by the
  same unit tests as the happy path.

## Risks and rollout
- No migration; ships behind the normal deploy.
- Sandbox smoke: call the endpoint for a shipped test order and an unshipped one.

## Open questions
1. Should the response include the carrier name alongside the tracking number?
   - [x] **Not yet.** Add it when a second carrier ships; today there is one.
   - [ ] **Include it now.** One extra column read, no new join.
