import unittest
from display_service.model import quota_rows

class QuotaDisplayTest(unittest.TestCase):
    def test_used_converted_to_remaining_with_no_fake_zero(self):
        rows=quota_rows({'codex':{'observedAt':100,'accounts':[{'fh':{'u':3},'sd':None}]}},100)
        self.assertEqual(rows[0]['value'],'97%')
        self.assertEqual(rows[0]['label'],'Codex 1')
        self.assertEqual(quota_rows({},100)[0]['value'],'--')

    def test_stale_quota_is_marked(self):
        rows=quota_rows({'cursor':{'observedAt':100,'percentages':{'totalPercentUsed':25}}},6000)
        row=next(x for x in rows if x['label']=='Cursor')
        self.assertEqual(row['status'],'stale')
        self.assertEqual(row['value'],'75%')

    def test_all_providers_and_error(self):
        d={'mimo':{'observedAt':100,'items':[{'remainingPercent':70.76}]},
           'jev':{'observedAt':100,'bal':{'amt':4.99,'cur':'USD'}},
           'cursor':{'observedAt':100,'lastError':'upstream failed','percentages':{'totalPercentUsed':10}}}
        rows={r['label']:r for r in quota_rows(d,100)}
        self.assertEqual(rows['MiMo']['value'],'71%')
        self.assertEqual(rows['Jev']['value'],'USD 4.99')
        self.assertEqual(rows['Cursor']['status'],'error')

    def test_malformed_numbers_do_not_crash_or_claim_available(self):
        rows=quota_rows({'codex':{'observedAt':100,'accounts':[{'fh':{'u':float('nan')}}]}},100)
        self.assertEqual(rows[0]['value'],'--')

if __name__=='__main__': unittest.main()
