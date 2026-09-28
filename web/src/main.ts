import { mount } from 'svelte';
import './styles/tokens.css';
import './styles/base.css';
import './styles/utilities.css';
import App from './App.svelte';
import { connection } from './lib/stores';

connection.start();

const target = document.getElementById('app');
if (!target) throw new Error('No #app element');

export default mount(App, { target });
