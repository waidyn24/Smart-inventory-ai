/** Requires running Docker application and installed browser: npx playwright install chromium */
import {test,expect} from '@playwright/test';
async function login(page:any){
 await page.goto('/login');
 await page.getByRole('button',{name:/Войти в Smart Inventory/}).click();
 await expect(page).toHaveURL(/dashboard/);
}
test('Owner sees a populated DEMO dashboard',async({page})=>{
 await login(page);
 await expect(page.getByText('Smart AI Insights')).toBeVisible();
 await expect(page.getByText('DEMO DATA')).toBeVisible();
 await expect(page.getByText('Капитал в остатках')).toBeVisible();
});
test('Cashier can find a product with barcode and record a sale',async({page})=>{
 await login(page);
 await page.goto('/pos');
 const barcode=page.getByPlaceholder('Отсканируйте EAN-13 или введите код…');
 await barcode.fill('2000000000015');await barcode.press('Enter');
 await expect(page.getByText('Молоко 1 л').last()).toBeVisible();
 await page.getByRole('button',{name:/Подтвердить продажу/}).click();
 await expect(page.getByText(/Продажа .* сохранена/)).toBeVisible();
});
test('Owner can inspect replenishment reasons and compare three digital twin scenarios',async({page})=>{
 await login(page);
 await page.goto('/purchases');
 await expect(page.getByRole('heading',{name:'Интеллектуальные закупки'})).toBeVisible();
 await expect(page.getByText('Почему именно столько?').first()).toBeVisible();
 await page.goto('/decision-twin');
 await expect(page.getByText('Сценарии закупки', {exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:/Рассчитать сценарии/}).click();
 await expect(page.getByText('Без закупки',{exact:true}).first()).toBeVisible();
 await expect(page.getByText('Рекомендованный заказ',{exact:true}).first()).toBeVisible();
 await expect(page.getByText('Бюджет / свои количества',{exact:true}).first()).toBeVisible();
});
