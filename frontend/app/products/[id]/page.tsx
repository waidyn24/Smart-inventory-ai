'use client';import {useParams} from 'next/navigation';import DashboardApp from '@/components/DashboardApp';
export default function ProductPage(){const params=useParams();return <DashboardApp section="products" selectedProductId={String(params.id)}/>}
