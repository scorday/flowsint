# Shared runtime configuration

`runtime-config.ts` is an unchanged snapshot of
`avl4-monorepo-ui/packages/runtime-config/src/index.ts`, revision
`061e98fd5c4fb1fe0efcef53657a7db6258e29cf`.

The shared module is distributed as dependency-free source rather than an npm
package. This copy keeps the separate Flowsint checkout/build self-contained.
Update it from the upstream source as a whole; application-specific behavior
belongs in `../runtime-config.ts`. It contains public configuration only.
