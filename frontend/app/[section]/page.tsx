'use client';import {useParams} from 'next/navigation';import DashboardApp from '@/components/DashboardApp';
export default function Section(){const p=useParams();return <DashboardApp section={String(p.section||'dashboard')}/>}
