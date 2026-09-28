import { Connection, serverUrl } from '../api/connection.svelte';
import { LinkStatusStore } from './linkStatus.svelte';
import { OutboundServersStore } from './outboundServers.svelte';
import { ServerSettingsStore } from './serverSettings.svelte';
import { SubscriptionLinksStore } from './subscriptionLinks.svelte';
import { TasksStore } from './tasks.svelte';

export const connection = new Connection(serverUrl());
export const serverSettings = new ServerSettingsStore(connection);
export const subscriptionLinks = new SubscriptionLinksStore(connection);
export const outboundServers = new OutboundServersStore(connection);
export const tasks = new TasksStore(connection);
export const linkStatus = new LinkStatusStore(connection, outboundServers);
