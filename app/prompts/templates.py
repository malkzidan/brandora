"""Fixed human-review/greeting wording shared by the canonical response planner."""
AR = {'GREETING': 'أهلاً بيك! أقدر أساعدك إزاي؟',
 'GREETING_SALAM': 'وعليكم السلام ورحمة الله وبركاته! أقدر أساعدك إزاي؟',
 'THANKYOU': 'العفو! لو عايز حاجة تانية أنا موجود.',
 'COMPLAINT_GENERIC': 'آسف على اللي حصل. ممكن تقولي إيه المشكلة بالظبط؟',
 'PAYMENT_DISPUTE': 'آسف على اللي حصل. ممكن تبعتلي رقم الطلب وطريقة الدفع ووقت '
                    'الدفع بالتقريب؟\n'
                    'ده بيساعد صاحب المحل يراجع الموضوع.',
 'LEGAL_THREAT': 'آسف إنك متضايق للدرجة دي. ممكن تكتبلي المشكلة بالتفصيل ورقم '
                 'الطلب لو موجود؟\n'
                 'ده بيساعد صاحب المحل يراجعها.',
 'CUSTOM_REQUEST': 'الطلبات المخصوصة بتتفق عليها مع صاحب المحل مباشرة.\n'
                   'ممكن تكتبلي تفاصيل اللي عايزه (الفكرة، الكمية، الميعاد)؟'}

EN = {'GREETING': 'Hi! How can I help you?',
 'GREETING_SALAM': 'Hi! How can I help you?',
 'THANKYOU': "You're welcome! Let me know if you need anything else.",
 'COMPLAINT_GENERIC': 'Sorry about that. Could you tell me exactly what the '
                      'problem is?',
 'PAYMENT_DISPUTE': 'Sorry about that. Could you send the order number, the '
                    'payment method and roughly when you paid?\n'
                    'That helps the store owner look into it.',
 'LEGAL_THREAT': "Sorry you're this upset. Could you describe the problem in "
                 'detail, with the order number if you have one?\n'
                 'That helps the store owner look into it.',
 'CUSTOM_REQUEST': 'Custom requests are agreed directly with the store owner.\n'
                   'Could you write the details of what you want (the idea, '
                   'quantity, timing)?'}

def t(lang,key,**kw):
    return (AR if lang == "ar" else EN)[key].format(**kw)
