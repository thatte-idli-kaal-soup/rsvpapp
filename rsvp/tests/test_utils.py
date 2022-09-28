from rsvp.utils import generate_password


def test_generate_password():
    assert (
        generate_password("Instagram-password", "this-is-a-salt")
        == "IWl20Ib$<nF=aAgHext2F)%V_G&W{1Gc"
    )
