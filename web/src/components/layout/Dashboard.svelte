<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    left: Snippet;
    center: Snippet;
    right: Snippet;
  }

  let { left, center, right }: Props = $props();
</script>

<!--
  Blocks move between columns with CSS only, so they are never re-created and
  keep what the user typed:
  - wide: left | center | right, each column scrolls on its own;
  - medium: center | side, where side holds the left and right blocks;
  - narrow: one column.
  Wrappers that are not columns at a width get display: contents, and the blocks
  inside are ordered by their --block-order.
-->
<main class="dashboard">
  <div class="zone center">{@render center()}</div>
  <div class="side">
    <div class="zone left">{@render left()}</div>
    <div class="zone right">{@render right()}</div>
  </div>
</main>

<style>
  .dashboard {
    --gap: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--gap);
    padding: var(--gap) var(--space-2);
  }

  .side,
  .zone {
    display: contents;
  }

  @media (min-width: 760px) {
    .dashboard {
      display: grid;
      /* The side column gives way first, so server rows stay on one line longer. */
      grid-template-columns: minmax(0, 1fr) clamp(260px, 30vw, 320px);
      grid-template-rows: minmax(0, 1fr);
      grid-template-areas: 'center side';
      flex: 1 1 auto;
      gap: 0;
      min-height: 0;
      padding: 0 calc(var(--gap) / 2);
    }

    .center,
    .side {
      position: relative;
      display: flex;
      flex-direction: column;
      gap: var(--gap);
      min-height: 0;
      padding: var(--gap) calc(var(--gap) / 2);
      overflow-y: auto;
    }

    .center {
      grid-area: center;
    }

    .side {
      grid-area: side;
    }
  }

  @media (min-width: 1200px) {
    .dashboard {
      grid-template-columns: minmax(250px, 300px) minmax(0, 1fr) minmax(250px, 300px);
      grid-template-areas: 'left center right';
    }

    .side {
      display: contents;
    }

    .left,
    .right {
      position: relative;
      display: flex;
      flex-direction: column;
      gap: var(--gap);
      min-height: 0;
      padding: var(--gap) calc(var(--gap) / 2);
      overflow-y: auto;
    }

    .left {
      grid-area: left;
    }

    .right {
      grid-area: right;
    }
  }
</style>
