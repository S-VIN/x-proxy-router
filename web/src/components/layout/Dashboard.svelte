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
      /*
       * The side blocks need about 320px for their rows to stay on one line; the
       * servers fold their rows into two lines when narrower.
       */
      grid-template-columns: minmax(0, 1fr) clamp(320px, 36vw, 360px);
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

  /* Three columns once the servers keep about as much room as with two. */
  @media (min-width: 1320px) {
    .dashboard {
      grid-template-columns: minmax(300px, 320px) minmax(0, 1fr) minmax(300px, 320px);
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
