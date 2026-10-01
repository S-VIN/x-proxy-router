import { Connection, serverUrl } from '../api/connection.svelte';
import { InboundServersStore } from './inboundServers.svelte';
import { LinkStatusStore } from './linkStatus.svelte';
import { OutboundServersStore } from './outboundServers.svelte';
import { RegFiltersStore } from './regFilters.svelte';
import { RoutingRulesStore } from './routingRules.svelte';
import { ServerSettingsStore } from './serverSettings.svelte';
import { SubscriptionLinksStore } from './subscriptionLinks.svelte';
import { TasksStore } from './tasks.svelte';

export const connection = new Connection(serverUrl());
export const serverSettings = new ServerSettingsStore(connection);
export const subscriptionLinks = new SubscriptionLinksStore(connection);
export const regFilters = new RegFiltersStore(connection);
export const outboundServers = new OutboundServersStore(connection);
export const inboundServers = new InboundServersStore(connection);
export const routingRules = new RoutingRulesStore(connection);
export const tasks = new TasksStore(connection);
export const linkStatus = new LinkStatusStore(connection, outboundServers);
