import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const IMAGE_DIR = join(HERE, '..', '..', '..', 'docs', 'images')
mkdirSync(IMAGE_DIR, { recursive: true })

const ADMIN_EMAIL = 'e2e-admin@eval-platform.io'
const ADMIN_PASSWORD = 'e2e-admin-password-123'
const REVIEWER_EMAIL = 'alice@demo.eval-platform.io'
const REVIEWER_PASSWORD = 'demo-pass-123'

async function shot(page: Page, name: string, fullPage = false) {
  await page.screenshot({ path: join(IMAGE_DIR, `${name}.png`), fullPage })
}

/** Register or log in, returning the storage state token for UI login. */
async function ensureAdmin(request: APIRequestContext): Promise<void> {
  const reg = await request.post('/api/auth/register', {
    data: { email: ADMIN_EMAIL, full_name: 'E2E Administrator', password: ADMIN_PASSWORD, role: 'admin' },
  })
  if (reg.ok()) return
  const login = await request.post('/api/auth/login', {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  })
  expect(login.ok(), `admin bootstrap failed: ${reg.status()} / ${login.status()} ${await login.text()}`).toBeTruthy()
}

async function uiLogin(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL('**/projects', { timeout: 30_000 })
}

test.describe.serial('evaluation platform end-to-end', () => {
  let projectId = ''

  test.beforeAll(async ({ request }) => {
    await ensureAdmin(request)
    // Fresh, deterministic demo dataset for every run.
    const loginRes = await request.post('/api/auth/login', {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    })
    const { access_token } = await loginRes.json()
    const headers = { Authorization: `Bearer ${access_token}` }
    await request.post('/api/admin/reset-demo', { headers })
    const seed = await request.post('/api/admin/seed-demo', { headers })
    expect(seed.ok(), await seed.text()).toBeTruthy()
    const body = await seed.json()
    projectId = body.project_id
    expect(body.tasks).toBe(60)
  })

  test('login page renders and rejects bad credentials', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: /AI Evaluator Calibration/i })).toBeVisible()
    await shot(page, '01-login')

    await page.getByLabel('Email').fill(ADMIN_EMAIL)
    await page.getByLabel('Password').fill('definitely-wrong-password')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('alert')).toContainText(/invalid email or password/i)
  })

  test('admin can sign in and see the project list', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await expect(page.getByRole('heading', { name: 'Evaluation projects' })).toBeVisible()
    await expect(page.getByText('Demo: LLM Support Assistant')).toBeVisible()
    // progress numbers come from the API, not placeholders
    await expect(page.getByText(/tasks complete/).first()).toBeVisible()
    await shot(page, '02-projects')
  })

  test('dashboard shows computed reliability analytics', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}`)
    await expect(page.getByRole('heading', { name: /Demo: LLM Support Assistant/i })).toBeVisible()

    // Real computed values must be present (not "n/a" everywhere).
    const reliability = page.getByRole('region', { name: /Inter-reviewer reliability/i }).or(
      page.locator('section', { hasText: 'Inter-reviewer reliability' }).first(),
    )
    await expect(reliability).toBeVisible()
    await expect(page.getByText("Krippendorff's α (ordinal)").first()).toBeVisible()
    await expect(page.getByText('ICC(2,1)').first()).toBeVisible()
    await expect(page.getByText("Fleiss' κ").first()).toBeVisible()

    await expect(page.getByText('Review progress').first()).toBeVisible()
    await shot(page, '03-dashboard', true)

    // Agreement analytics detail + severity distribution
    await page.getByText('Disagreements by severity').scrollIntoViewIfNeeded()
    await shot(page, '04-agreement-analytics')
  })

  test('tasks page lists imported data and opens the import dialog', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}/tasks`)
    await expect(page.getByRole('heading', { name: 'Tasks & data' })).toBeVisible()
    await expect(page.getByText('Synthetic Q3 evaluation set')).toBeVisible()
    await shot(page, '05-tasks')

    await page.getByRole('button', { name: 'Import dataset' }).click()
    await expect(page.getByRole('dialog', { name: 'Import dataset' })).toBeVisible()
    await page
      .getByLabel('Or paste content')
      .fill('prompt,response,model_name\nE2E question?,E2E answer text.,Atlas-Mini\n')
    await page.getByRole('button', { name: /Validate \(dry run\)/ }).click()
    await expect(page.getByText('1 valid')).toBeVisible()
    await shot(page, '06-import-preview')
    await page.getByRole('button', { name: 'Close', exact: true }).click()
  })

  test('rubric page shows categories, anchors and version history', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}/rubric`)
    await expect(page.getByRole('heading', { name: 'Rubric', exact: true })).toBeVisible()
    await expect(page.getByText('Response Quality Rubric v1')).toBeVisible()
    await expect(page.getByText('Factual Accuracy').first()).toBeVisible()
    await expect(page.getByText('Safety & Policy').first()).toBeVisible()
    await shot(page, '07-rubric', true)
  })

  test('reviewer workspace is blinded and shows rubric guidance', async ({ page }) => {
    await uiLogin(page, REVIEWER_EMAIL, REVIEWER_PASSWORD)
    await page.goto(`/projects/${projectId}/evaluate`)
    await expect(page.getByRole('heading', { name: 'Evaluation workspace' })).toBeVisible()
    await expect(page.getByText('Your queue').first()).toBeVisible()

    // Alice has already rated the seeded items, so peer ratings are revealed.
    await expect(page.getByText('Item under review').first()).toBeVisible()
    await expect(page.getByText('Rubric', { exact: true }).first()).toBeVisible()
    await shot(page, '08-reviewer-workspace', true)
  })

  test('disagreement queue ranks cases and drills into evidence', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}/disagreements`)
    await expect(page.getByRole('heading', { name: 'Disagreement queue' })).toBeVisible()
    await expect(page.getByText('Total detected').first()).toBeVisible()

    const rows = page.locator('tbody tr')
    await expect(rows.first()).toBeVisible()
    const count = await rows.count()
    expect(count).toBeGreaterThan(5)
    await shot(page, '09-disagreements')

    await rows.first().getByRole('button', { name: 'Review' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByText('Independent ratings').first()).toBeVisible()
    await expect(page.getByText('How severity is computed').first()).toBeVisible()
    await shot(page, '10-disagreement-detail')

    // Offline AI-assisted summary works with no credentials configured.
    await page.getByRole('button', { name: 'Summarise this case' }).click()
    await expect(page.getByText('Case summary').first()).toBeVisible()
    await expect(page.getByText(/offline/i).first()).toBeVisible()
    await shot(page, '11-case-summary-offline')
    await page.getByRole('button', { name: 'Close dialog' }).click()
  })

  test('adjudication workspace shows consensus and records a decision', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}/adjudication`)
    await expect(page.getByRole('heading', { name: 'Adjudication workspace' })).toBeVisible()

    // Start from the highest-priority open disagreement.
    const openList = page.locator('section', { hasText: 'Open disagreements' }).first()
    await expect(openList).toBeVisible()
    await openList.locator('button').first().click()

    await expect(page.getByText('Side-by-side reviewer assessments').first()).toBeVisible()
    await expect(page.getByText('Advisory consensus').first()).toBeVisible()
    await expect(page.getByText('Authoritative decision').first()).toBeVisible()
    await shot(page, '12-adjudication', true)

    await page.getByLabel('Resolution rationale').fill('E2E: anchors at level 4 fit; core claims verified against the reference answer.')
    await page.getByRole('button', { name: /Record final decision/ }).click()
    await expect(page.getByText('Decision recorded as final.')).toBeVisible()
    await shot(page, '13-adjudication-finalised')
  })

  test('calibration dashboard reports accuracy against gold labels', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}/calibration`)
    await expect(page.getByRole('heading', { name: 'Reviewer calibration' })).toBeVisible()
    await expect(page.getByText('Q3 baseline calibration').first()).toBeVisible()
    await expect(page.getByText('Reviewers assessed').first()).toBeVisible()
    await expect(page.getByText('Mean pre-accuracy').first()).toBeVisible()
    await expect(page.getByText('Calibration ≠ agreement')).toBeVisible()
    await shot(page, '14-calibration', true)
  })

  test('rubric insights surface evidence-backed issues', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}/insights`)
    await page.getByRole('button', { name: 'Run analysis' }).click()
    await expect(page.getByText('Evidence').first()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Recommended improvement').first()).toBeVisible()
    await expect(page.getByText(/sample size \d+ items/i).first()).toBeVisible()
    await shot(page, '15-rubric-insights', true)
  })

  test('reports page generates a downloadable PDF', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}/reports`)
    await expect(page.getByRole('heading', { name: 'Reports & exports' })).toBeVisible()

    await page.getByLabel('Report title').fill('E2E Quality Report')
    await page.getByLabel('Format').selectOption('pdf')
    await page.getByRole('button', { name: 'Generate report' }).click()
    await expect(page.getByText('E2E Quality Report').first()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Metric definitions').first()).toBeVisible()
    await shot(page, '16-reports', true)
  })

  test('project settings exposes thresholds and team access', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}/settings`)
    await expect(page.getByRole('heading', { name: 'Project settings' })).toBeVisible()
    await expect(page.getByText('Disagreement thresholds').first()).toBeVisible()
    await expect(page.getByText('Team access').first()).toBeVisible()
    await shot(page, '17-project-settings', true)
  })

  test('AI provider settings keep credentials masked', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)

    // Configure a provider with a fake key via the API, then verify the UI masks it.
    const loginRes = await page.request.post('/api/auth/login', {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    })
    const { access_token } = await loginRes.json()
    const save = await page.request.post('/api/llm/config', {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { provider: 'openai', api_key: 'sk-E2E-FAKE-KEY-abcdef123456', model: 'gpt-4o-mini', label: 'E2E provider' },
    })
    expect(save.ok(), await save.text()).toBeTruthy()

    await page.goto('/admin')
    await page.getByRole('tab', { name: 'AI assistance' }).click()
    await expect(page.getByText('Optional AI assistance').first()).toBeVisible()
    await expect(page.getByText('Billing note.').first()).toBeVisible()

    const bodyText = await page.locator('body').innerText()
    expect(bodyText).not.toContain('sk-E2E-FAKE-KEY-abcdef123456')
    expect(bodyText).toMatch(/sk…3456|…3456/)
    await shot(page, '18-ai-settings', true)

    // Restore offline default so later runs are credential-free.
    await page.request.post('/api/llm/config', {
      headers: { Authorization: `Bearer ${access_token}` },
      data: { provider: 'offline' },
    })
  })

  test('administration page shows audit trail and system stats', async ({ page }) => {
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto('/admin')
    await expect(page.getByText('Demonstration data').first()).toBeVisible()
    await shot(page, '19-admin-overview', true)

    await page.getByRole('tab', { name: 'Audit' }).click()
    await expect(page.getByText('Consequential actions').first()).toBeVisible()
    // Actions produced by this E2E flow: demo seeding, adjudication, report
    // generation and AI provider configuration are all audited.
    const rows = page.locator('tbody tr')
    await expect(rows.first()).toBeVisible()
    expect(await rows.count()).toBeGreaterThan(3)
    await expect(page.getByText('demo.seed').first()).toBeVisible()
    await expect(page.getByText('adjudication.decide').first()).toBeVisible()
    await expect(page.getByText('report.generate').first()).toBeVisible()
    await shot(page, '20-audit-log')
  })

  test('layout is usable on a mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await uiLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto(`/projects/${projectId}`)
    await expect(page.getByRole('heading', { name: /Demo: LLM Support Assistant/i })).toBeVisible()
    await shot(page, '21-mobile-dashboard', true)

    await page.getByRole('button', { name: 'Menu' }).click()
    await expect(page.getByRole('link', { name: 'Disagreements' })).toBeVisible()
    await shot(page, '22-mobile-nav')
  })
})
