# Frontend

This field says whether the repository has a frontend and which kind, so the plan
knows when a ticket changes screens, where the look comes from when the kit draws
them, and what the plan's layers and the review's Contracts table should name. With
`none` the plan never carries a Designs section and the design step is skipped.

The design step is the same for every value: when the ticket changes a screen and the
tracker context carries no design link or image, the plan makes a Design canvas
(`/design` when Claude Code offers it, else the Artifact tool's Design canvas type),
one static artboard per screen state the Specs reach, and embeds them in the plan's
Designs section. The value below decides where the look comes from when no design
system is attached, and what the artboards should resemble.

## none

**Plan** - No frontend in this repository. Never add a Designs section and never make
a canvas; a ticket that mentions a screen belongs to another repository, so say so in
Context and plan the API side only.

**Review** - Nothing to coordinate on the frontend side. A contract row still names
the external client that has to move when an API shape changes.

**Common findings**
- View models or DTOs shaped for a UI that does not live here.

## blazor

**Plan** - Name each new or changed `.razor` component by path (`Components/Pages/`
for routable pages, `Components/Shared/` or `Components/Layout/` for the rest), its
`@page` route, its parameters and the service it injects. Say which render mode it
takes (`@rendermode InteractiveServer`, `InteractiveWebAssembly`, `InteractiveAuto` or
static SSR) because that decides where the handler runs. The look comes from
`wwwroot/app.css` or `wwwroot/css/app.css`, `MainLayout.razor` and any
`<Component>.razor.css` isolation file; an artboard should match those colours, spacing
and the layout's navigation.

**Review** - One row per component whose parameters, events or route changed and per
API the frontend calls: the request and response shape, and whether the WebAssembly
client and the server ship together or separately.

**Common findings**
- A component that reads `DbContext` or a repository directly instead of a service or
  an API.
- An interactive render mode on a page that only displays data.
- `IJSRuntime` calls during prerender, or a `DotNetObjectReference` never disposed.
- Missing `@key` on lists that reorder, so edits land on the wrong row.

## razor

**Plan** - Name each new or changed Razor Page (`Pages/<Area>/<Name>.cshtml` with its
`PageModel`) or MVC view and action (`Controllers/<Name>Controller.cs`,
`Views/<Name>/<Action>.cshtml`), the handler method (`OnGet`, `OnPost<Name>`) and the
view model it binds. Partial views, view components and tag helpers count as
components. The look comes from `Views/Shared/_Layout.cshtml` or
`Pages/Shared/_Layout.cshtml` and `wwwroot/css/site.css`; an artboard should match
the layout's header, navigation and Bootstrap or custom classes in use.

**Review** - One row per route, handler or view model change, and per form whose
field names changed, since model binding and any script under `wwwroot/js` depend on
them.

**Common findings**
- Business logic in the `PageModel` or controller action instead of Application.
- A POST handler without the anti-forgery token or the `[ValidateAntiForgeryToken]`
  attribute.
- A view model that exposes the entity directly.
- Redirect after POST missing, so a refresh resubmits the form.

## react

**Plan** - Name the SPA project root (`ClientApp/`, `src/<Name>.Web/client/` or a
separate folder) and each new or changed component and route by path under `src/`,
with its props and the API hook or service it calls. Say whether state is local,
context or a store, and which query or fetch layer the project uses. The look comes
from the project's theme or global stylesheet (`src/index.css`, `src/App.css`, a
Tailwind config or a component library's theme file); an artboard should match its
tokens and existing components.

**Review** - One row per API the client calls with its request and response shape,
one per shared type or generated client that has to be regenerated, and whether the
SPA deploys with the .NET host or on its own.

**Common findings**
- A component that fetches in render or without cancelling on unmount.
- Types duplicated by hand instead of generated from the OpenAPI document.
- Missing loading, empty and error states for a call that can fail.
- Keys derived from array index on lists that reorder.

## angular

**Plan** - Name the project root (`ClientApp/` or a separate folder) and each new or
changed component, service and route by path under `src/app/`, with its inputs,
outputs and the service it injects. Say whether the component is standalone and
which module or route declares it. The look comes from `src/styles.scss` and the
Angular Material or custom theme in use; an artboard should match its palette,
typography and existing components.

**Review** - One row per API the client calls with its request and response shape,
one per generated client or shared interface that has to be regenerated, and whether
the app ships with the .NET host or separately.

**Common findings**
- HTTP calls inside a component instead of a service.
- Subscriptions never unsubscribed or not using the async pipe.
- `any` on API responses instead of generated interfaces.
- Missing loading, empty and error states for a call that can fail.

## vue

**Plan** - Name the project root (`ClientApp/` or a separate folder) and each new or
changed single-file component, composable and route by path under `src/`, with its
props, emits and the API composable it calls. Say whether state lives in the
component, a composable or a Pinia store. The look comes from `src/assets/` styles
and the component library's theme in use; an artboard should match its tokens and
existing components.

**Review** - One row per API the client calls with its request and response shape,
one per generated client or shared type that has to be regenerated, and whether the
app ships with the .NET host or separately.

**Common findings**
- Fetching inside a component instead of a composable or store.
- Reactive state mutated from outside its owner.
- Types duplicated by hand instead of generated from the OpenAPI document.
- Missing loading, empty and error states for a call that can fail.

## javascript

**Plan** - Script-driven pages without a framework: plain JavaScript or TypeScript
under `wwwroot/js/` or `Scripts/`, jQuery, or a bundle built from `package.json`.
Name each new or changed script by path, the page or view it attaches to, the
elements it binds by id or class, and the endpoint it calls. The look comes from the
server-rendered layout and `wwwroot/css/site.css`; an artboard should match that
layout with the script's states drawn in.

**Review** - One row per endpoint the scripts call with its request and response
shape, and one per element id or class a script depends on that a view change
renamed.

**Common findings**
- Element ids or classes referenced in a script but absent from the view.
- Fetch calls without error handling or without the anti-forgery header on POST.
- Global functions and state on `window` instead of a module.
- Inline scripts in views that a content security policy would block.
