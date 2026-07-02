import unittest
import ssl_utils

class TestSafetyNumbers(unittest.TestCase):
    def test_safety_number_consistency(self):
        fp1 = "a" * 64
        fp2 = "b" * 64

        sn1 = ssl_utils.get_safety_number(fp1, fp2)
        sn2 = ssl_utils.get_safety_number(fp2, fp1)

        self.assertEqual(sn1, sn2)
        self.assertEqual(len(sn1.replace("-", "")), 30)
        self.assertTrue(sn1.replace("-", "").isdigit())

    def test_safety_number_uniqueness(self):
        fp1 = "a" * 64
        fp2 = "b" * 64
        fp3 = "c" * 64

        sn12 = ssl_utils.get_safety_number(fp1, fp2)
        sn13 = ssl_utils.get_safety_number(fp1, fp3)

        self.assertNotEqual(sn12, sn13)

if __name__ == '__main__':
    unittest.main()
